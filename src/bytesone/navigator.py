"""BytsOne navigator — courses → chapters → problems → Take Challenge → Mark Complete."""

import re
import time
from typing import List, Dict, Optional
from playwright.sync_api import Page, TimeoutError as PWTimeout

from src.config.constants import (
    BYTESONE_CHALLENGE, COURSE_TITLE_FRAGMENTS,
    BYTESONE_COURSES_URL, TIMEOUT_SHORT, TIMEOUT_MEDIUM, TIMEOUT_LONG,
)
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9\s-]", "", text.lower().strip())
    return re.sub(r"\s+", "-", s).strip("-")


class BytesOneNavigator:
    def __init__(self, page: Page):
        from src.config.settings import settings
        self.page = page
        self.settings = settings
        self._current_problem_url: Optional[str] = None  # saved before Take Challenge
        self._course_url_cache: Dict[str, str] = {}       # course_key → course URL

    # ── 1. Open course ─────────────────────────────────────────────────────────

    def open_course(self, course_key: str) -> bool:
        """Navigate to the course curriculum page. Returns True on success."""
        fragment = COURSE_TITLE_FRAGMENTS[course_key]

        # ── Fast path: cached URL from a previous discovery this session ───────
        if course_key in self._course_url_cache:
            cached_url = self._course_url_cache[course_key]
            logger.info(f"Opening course: {fragment} (cached URL)")
            self.page.goto(cached_url)
            self.page.wait_for_load_state("load")
            self.page.wait_for_timeout(2_000)
            if "/home/course/" in self.page.url:
                logger.info(f"Opened course: {fragment} ✅  URL: {self.page.url}")
                return True
            # Cache miss — fall through to re-discover
            logger.warning("Cached URL no longer valid — re-discovering course")
            del self._course_url_cache[course_key]

        logger.info(f"Opening course: {fragment} (discovering…)")
        self.page.goto(BYTESONE_COURSES_URL)
        self.page.wait_for_load_state("load")

        # BytsOne is a React SPA — content renders after the load event.
        # Wait for at least one "Continue Learning" button to appear before scanning.
        try:
            self.page.wait_for_selector(
                "button:has-text('Continue Learning'), a:has-text('Continue Learning')",
                timeout=15_000,
            )
        except PWTimeout:
            logger.warning("Course cards slow to render — waiting extra 3s")
            self.page.wait_for_timeout(3_000)

        # Build ordered list of candidate cards: date-hinted ones FIRST
        date_hint = getattr(self.settings, "course_date_hint", "")
        all_cards = self.page.locator("div").all()
        primary_card   = None  # card matching fragment + date_hint
        fallback_card  = None  # card matching fragment only

        for card in all_cards:
            try:
                text = card.inner_text(timeout=300).strip()
                if fragment not in text or len(text) > len(fragment) + 150:
                    continue
                if date_hint and date_hint in text:
                    primary_card = card
                    break           # exact match — stop searching
                if fallback_card is None:
                    fallback_card = card
            except Exception:
                continue

        target_card = primary_card or fallback_card
        if primary_card:
            logger.info(f"Matched course card with date hint '{date_hint}'")
        elif fallback_card:
            logger.warning(f"Date hint '{date_hint}' not found — using first '{fragment}' card")

        if target_card is None:
            logger.error(f"Course card not found: {fragment}")
            return False

        # Click "Continue Learning" scoped to that card
        clicked = False
        for btn_text in ["Continue Learning", "Start Learning", "Start"]:
            try:
                btn = target_card.locator(f"button:has-text('{btn_text}'), a:has-text('{btn_text}')").first
                btn.wait_for(state="visible", timeout=TIMEOUT_SHORT)
                btn.click()
                clicked = True
                break
            except PWTimeout:
                continue

        if not clicked:
            logger.warning("Continue Learning not found — clicking card itself")
            target_card.click()

        self.page.wait_for_load_state("load")
        self.page.wait_for_timeout(2_000)
        final_url = self.page.url
        logger.info(f"Opened course: {fragment} ✅  URL: {final_url}")

        # Verify we landed on a course page (not still on courses list)
        if "/home/course/" not in final_url and "/home/courses" in final_url:
            logger.error(f"Navigation failed — still on courses page: {final_url}")
            return False

        # Cache the URL so future re-opens navigate here directly
        self._course_url_cache[course_key] = final_url
        return True

    # ── 2. Chapters ────────────────────────────────────────────────────────────

    def get_chapters(self) -> List[Dict]:
        """
        Find all Day N chapter rows in the sidebar.
        Strategy:
          1. Wait up to 10s for at least one 'Day' element to appear.
          2. JS-evaluate the sidebar to collect all day rows cleanly.
          3. Python fallback: walk all text nodes, no % requirement.
        """
        self.page.wait_for_load_state("load")

        # Wait for Day elements to appear (SPA may be slow)
        try:
            self.page.wait_for_selector("*:has-text('Day 1')", timeout=10_000)
        except PWTimeout:
            logger.warning("Timeout waiting for Day 1 element — page may not have rendered")
        self.page.wait_for_timeout(1_000)

        # ── Strategy 1: JS scan — finds day rows even without "%" text ──────────
        chapters = self._get_chapters_via_js()
        if chapters:
            chapters.sort(key=lambda c: c["day_num"])
            logger.info(
                "Chapters found: "
                + ", ".join(
                    f"{c['label']}({c['progress_pct']}%{'🔒' if c['locked'] else ''})"
                    for c in chapters
                )
            )
            return chapters

        # ── Strategy 2: Python fallback ─────────────────────────────────────────
        logger.warning("JS chapter scan returned nothing — trying Python fallback")
        chapters = self._get_chapters_python_fallback()
        chapters.sort(key=lambda c: c["day_num"])
        logger.info(
            "Chapters found (fallback): "
            + ", ".join(
                f"{c['label']}({c['progress_pct']}%{'🔒' if c['locked'] else ''})"
                for c in chapters
            )
        )
        return chapters

    def _get_chapters_via_js(self) -> List[Dict]:
        """Use JS to collect all Day N rows from the sidebar (no % required)."""
        raw = self.page.evaluate(
            r"""
            () => {
                const results = [];
                const seen = new Set();
                // Match any element whose own text starts with "Day <digit>"
                const all = Array.from(document.querySelectorAll('*'));
                for (const el of all) {
                    // Only look at leaf-ish elements (not huge containers)
                    const directText = Array.from(el.childNodes)
                        .filter(n => n.nodeType === 3)
                        .map(n => n.textContent.trim())
                        .join(' ')
                        .trim();
                    const fullText = (el.textContent || '').trim().replace(/\s+/g, ' ');
                    // Accept if direct text OR full inner text starts with Day N
                    const candidate = directText || fullText;
                    const m = candidate.match(/^Day\s+(\d+)/);
                    if (!m) continue;
                    const dayNum = parseInt(m[1]);
                    if (dayNum < 1 || dayNum > 9 || seen.has(dayNum)) continue;
                    // Skip elements that are clearly big containers (too much text)
                    if (fullText.length > 200) continue;
                    seen.add(dayNum);
                    const pctM = fullText.match(/(\d+)%/);
                    const pct = pctM ? parseInt(pctM[1]) : 0;
                    const html = el.innerHTML || '';
                    const locked = html.toLowerCase().includes('lock');
                    results.push({ dayNum, pct, locked, text: fullText.substring(0, 80) });
                }
                return results;
            }
            """
        )
        chapters = []
        seen = set()
        for r in (raw or []):
            day_num = r["dayNum"]
            if day_num in seen:
                continue
            seen.add(day_num)
            pct = r["pct"]
            locked = r["locked"]
            # Re-find the element via Playwright for clicking
            el = self.page.locator(f"*:has-text('Day {day_num}')").last
            chapters.append({
                "label":        f"Day {day_num}",
                "day_num":      day_num,
                "locked":       locked and pct == 0,
                "completed":    pct == 100,
                "progress_pct": pct,
                "element":      el,
            })
        return chapters

    def _get_chapters_python_fallback(self) -> List[Dict]:
        """Pure Python: walk all elements for Day N text, no % filter."""
        seen_days: set = set()
        chapters: List[Dict] = []
        for el in self.page.locator("*:has-text('Day ')").all():
            try:
                text = el.inner_text(timeout=300).strip()
            except Exception:
                continue
            m = re.match(r"^Day\s+(\d+)", text)
            if not m:
                continue
            day_num = int(m.group(1))
            if day_num < 1 or day_num > 9 or day_num in seen_days or len(text) > 200:
                continue
            seen_days.add(day_num)
            pct = 0
            m_pct = re.search(r"(\d+)%", text)
            if m_pct:
                pct = int(m_pct.group(1))
            try:
                html = el.inner_html(timeout=300)
                locked = "lock" in html.lower()
            except Exception:
                locked = False
            chapters.append({
                "label":        f"Day {day_num}",
                "day_num":      day_num,
                "locked":       locked and pct == 0,
                "completed":    pct == 100,
                "progress_pct": pct,
                "element":      el,
            })
        return chapters

    def click_chapter(self, chapter: Dict) -> bool:
        """
        Click a day chapter to expand it.
        If the chapter is already expanded (problems already visible), skip the click
        to avoid collapsing it (BytsOne toggles on click).
        """
        day_num = chapter["day_num"]
        label   = chapter["label"]

        # Check if chapter is already expanded — peek at problems WITHOUT clicking
        self.page.wait_for_timeout(800)
        already_expanded = self._chapter_is_expanded(day_num)
        if already_expanded:
            logger.debug(f"{label} already expanded — skipping click")
            return True

        try:
            chapter["element"].scroll_into_view_if_needed()
            chapter["element"].click()
            self.page.wait_for_load_state("load")
            self.page.wait_for_timeout(1_500)
            return True
        except Exception as e:
            logger.error(f"Could not click chapter {label}: {e}")
            return False

    def _chapter_is_expanded(self, day_num: int) -> bool:
        """Return True if the day panel already shows ≥1 problem items."""
        try:
            for pattern in [
                f"text={day_num}. Day {day_num}",
                f"text=Day {day_num}",
            ]:
                locs = self.page.locator(pattern).all()
                if not locs:
                    continue
                heading = locs[-1]
                # Walk up to find sibling/child list
                result = self.page.evaluate(
                    """(el) => {
                        let c = el.parentElement;
                        for (let i = 0; i < 6; i++) {
                            if (!c) break;
                            const items = c.querySelectorAll('li');
                            if (items.length >= 1) return true;
                            c = c.parentElement;
                        }
                        return false;
                    }""",
                    heading.element_handle(),
                )
                if result:
                    return True
        except Exception:
            pass
        return False

    # ── 3. Problems ────────────────────────────────────────────────────────────

    def get_problems_in_chapter(self, day_num: int) -> List[Dict]:
        r"""
        After clicking a chapter, the right panel shows the day's problems.
        KEY: scope search to the container that has the 'N. Day N' heading.
        Problem items have circle indicators (no "%" text, no nav labels).
        """
        self.page.wait_for_timeout(1_500)

        # Find the day heading in the content area.
        # Try several patterns — actual format varies by platform version.
        heading_loc = None
        tried_patterns = []
        for pattern in [
            f"text={day_num}. Day {day_num}",
            f"*:has-text('{day_num}. Day {day_num}')",
            f"text=Day {day_num}",
            f"h1:has-text('Day {day_num}')",
            f"h2:has-text('Day {day_num}')",
            f"h3:has-text('Day {day_num}')",
            f"[class*='title']:has-text('Day {day_num}')",
            f"[class*='heading']:has-text('Day {day_num}')",
        ]:
            tried_patterns.append(pattern)
            try:
                locs = self.page.locator(pattern).all()
                if locs:
                    heading_loc = locs[-1]  # last = content area, not sidebar
                    logger.debug(f"Day heading found with pattern: {pattern!r}")
                    break
            except Exception:
                continue

        if heading_loc is None:
            # Dump all visible text to help diagnose what the page looks like
            try:
                sample = self.page.evaluate(
                    "() => document.body.innerText.substring(0, 800)"
                )
                logger.warning(
                    f"Could not find heading for Day {day_num}.\n"
                    f"  Tried: {tried_patterns}\n"
                    f"  Page text sample: {sample!r}"
                )
            except Exception:
                logger.warning(f"Could not find heading 'Day {day_num}'")
            return self._problems_fallback()

        # Walk UP from heading to find the panel containing the problem list.
        # Look for li OR div/a children — different platforms use different tags.
        problems_data = self.page.evaluate(
            """
            (headingEl) => {
                if (!headingEl) return { debug: 'no element', items: [] };

                // Walk up to find a container with several child elements
                let container = headingEl.parentElement;
                let walkLog = [];
                for (let i = 0; i < 8; i++) {
                    if (!container) break;
                    const items = container.querySelectorAll('li, a[href], div[class*="item"], div[class*="lesson"], div[class*="problem"]');
                    walkLog.push(`depth=${i} tag=${container.tagName} class=${container.className} items=${items.length}`);
                    if (items.length >= 2) break;
                    container = container.parentElement;
                }

                if (!container) return { debug: 'no container. walk: ' + walkLog.join(' | '), items: [] };

                const results = [];
                const seen = new Set();
                const _NAV = new Set([
                    'dashboard','overall report','assessments','contest calendar',
                    'mentoring support','global platform assessments','courses',
                    'dsa sheets','explore','certificates','live session','ide',
                    'ai interview','resume builder','gps leaderboard','log out','back',
                    'completed','schedule',  // skip non-problem items
                ]);
                const _SKIP_PHRASES = [
                    'complete all previous',
                    'to proceed',
                    'locked',
                    'coming soon',
                ];

                // Try li first, then divs with item/lesson/problem class
                const candidates = Array.from(
                    container.querySelectorAll('li, div[class*="item"], div[class*="lesson"], div[class*="problem"], a[href]')
                );

                candidates.forEach(el => {
                    const rawText = el.textContent || '';
                    const text = rawText.trim().replace(/\\n/g, ' ').replace(/\\s+/g, ' ');

                    if (!text || text.length < 3 || text.length > 120) return;
                    if (/^Day\\s+\\d/.test(text)) return;     // skip day headers
                    if (/\\d+%/.test(text)) return;           // skip progress %
                    if (_NAV.has(text.toLowerCase())) return; // skip nav labels
                    if (_SKIP_PHRASES.some(p => text.toLowerCase().includes(p))) return;
                    if (seen.has(text)) return;
                    seen.add(text);

                    const html = el.innerHTML || '';
                    const hasCheck = html.includes('check') ||
                                     html.includes('complete') ||
                                     html.includes('done') ||
                                     el.querySelector('svg circle[fill]') !== null;

                    results.push({ title: text, completed: hasCheck });
                });

                return { debug: 'container: ' + container.tagName + '.' + container.className + ' walk: ' + walkLog.join(' | '), items: results };
            }
            """,
            heading_loc.element_handle(),
        )

        # problems_data is now { debug: str, items: [...] }
        debug_info = problems_data.get("debug", "") if isinstance(problems_data, dict) else ""
        items = problems_data.get("items", []) if isinstance(problems_data, dict) else []

        if not items:
            logger.warning(
                f"No problems found via JS for Day {day_num}. Debug: {debug_info}"
            )
            return self._problems_fallback()

        logger.debug(f"Day {day_num} JS container debug: {debug_info}")

        problems = []
        for p in items:
            title = p["title"].strip()
            if not title:
                continue
            problems.append({
                "title":      title,
                "problem_id": _slugify(title),
                "completed":  p["completed"],
                "element":    self.page.locator(f"li:has-text('{title}'), div:has-text('{title}')").last,
            })

        logger.info(
            f"Day {day_num} problems: "
            + ", ".join(f"{p['title']}({'✓' if p['completed'] else '○'})" for p in problems)
        )
        return problems

    def _problems_fallback(self) -> List[Dict]:
        """Last-resort: any visible li text that doesn't look like a nav item."""
        _NAV = {
            "dashboard", "overall report", "assessments", "contest calendar",
            "mentoring support", "global platform assessments", "courses",
            "dsa sheets", "explore", "certificates", "live session", "ide",
            "ai interview", "ai interview (new)", "resume builder",
            "gps leaderboard", "log out", "back", "completed", "schedule",
        }
        _SKIP_PHRASES = ["complete all previous", "to proceed", "locked", "coming soon"]
        results = []
        seen = set()
        for li in self.page.locator("li").all():
            try:
                t = li.inner_text().strip()
                if not t or t.lower() in _NAV or re.match(r"^Day\s+\d", t) or "%" in t:
                    continue
                if any(p in t.lower() for p in _SKIP_PHRASES):
                    continue
                if t in seen:
                    continue
                seen.add(t)
                results.append({
                    "title":      t,
                    "problem_id": _slugify(t),
                    "completed":  False,
                    "element":    li,
                })
            except Exception:
                continue
        return results

    def click_problem(self, problem: Dict) -> bool:
        """
        Click a problem row by re-finding it by title (never uses stale element ref).
        """
        self._current_problem_url = self.page.url
        title = problem["title"]
        # Escape single quotes for the CSS selector
        safe_title = title.replace("'", "\\'")
        selectors = [
            f"li:has-text('{safe_title}')",
            f"div[class*='problem']:has-text('{safe_title}')",
            f"div[class*='lesson']:has-text('{safe_title}')",
            f"div[class*='item']:has-text('{safe_title}')",
            f"*:has-text('{safe_title}')",
        ]
        for sel in selectors:
            try:
                els = self.page.locator(sel).all()
                # Pick the smallest element (most specific match)
                best = None
                for el in els:
                    try:
                        t = el.inner_text(timeout=300).strip()
                        if title in t and len(t) < len(title) + 60:
                            best = el
                            break
                    except Exception:
                        continue
                if best:
                    best.scroll_into_view_if_needed()
                    best.click()
                    self.page.wait_for_load_state("load")
                    self.page.wait_for_timeout(1_000)
                    logger.debug(f"Opened problem: {title}  URL: {self.page.url}")
                    return True
            except Exception:
                continue
        logger.error(f"Could not click problem '{title}'")
        return False

    # ── 4. Take Challenge ──────────────────────────────────────────────────────

    def click_activate(self) -> bool:
        """
        Click the 'Activate' button if present (for new/unattempted problems).
        Returns True if clicked or if button not found (already activated).
        """
        activate_selectors = [
            "button:has-text('Activate')",
            "a:has-text('Activate')",
            "[class*='activate']",
        ]
        
        for sel in activate_selectors:
            try:
                btn = self.page.locator(sel).first
                btn.wait_for(state="visible", timeout=TIMEOUT_SHORT)
                btn.click()
                logger.info("Clicked 'Activate' ✅")
                self.page.wait_for_timeout(2_000)  # Wait for activation to complete
                return True
            except PWTimeout:
                continue
        
        logger.debug("'Activate' button not found — problem may already be activated")
        return True  # Not an error - just already activated

    def click_take_challenge(self) -> bool:
        """
        Click the 'Take Challenge' button.
        Retries a few times so the SPA has time to render the problem detail panel.
        """
        self._current_problem_url = self.page.url   # save for return trip
        sel = BYTESONE_CHALLENGE["take_challenge"]
        for attempt in range(3):
            try:
                btn = self.page.locator(sel).first
                btn.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
                btn.click()
                logger.info("Clicked 'Take Challenge'")
                self.page.wait_for_timeout(1_500)
                return True
            except PWTimeout:
                if attempt < 2:
                    logger.debug(f"'Take Challenge' not visible yet (attempt {attempt+1}/3) — waiting 3s")
                    self.page.wait_for_timeout(3_000)
                continue
        logger.error("'Take Challenge' button not found")
        return False

    def handle_contest_dialog(self) -> bool:
        """
        Auto-confirm the LeetCode Contest dialog:
          Step 1: 'Continue' button (confirm username)  
          Step 2: checkbox + 'Start Contest'
        """
        # Wait for dialog to appear
        self.page.wait_for_timeout(2_000)
        
        # Step 1 — Continue (username confirmation)
        try:
            btn = self.page.locator(BYTESONE_CHALLENGE["dialog_continue_btn"]).first
            btn.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
            btn.click()
            logger.debug("Dialog step 1: Continue clicked")
            self.page.wait_for_timeout(1_500)
        except PWTimeout:
            logger.debug("No Continue button — skipping to step 2")

        # Step 2 — checkbox + Start Contest
        # Try multiple strategies for the checkbox
        checkbox_checked = False
        
        # Strategy 1: Find checkbox by type
        checkbox_selectors = [
            "input[type='checkbox']",
            "input[type='checkbox'][id]",
            "[role='checkbox']",
            "div[role='checkbox']",
            "span:has(input[type='checkbox'])",
        ]
        
        for sel in checkbox_selectors:
            try:
                cb = self.page.locator(sel).first
                cb.wait_for(state="visible", timeout=TIMEOUT_SHORT)
                
                # Check if it's already checked
                is_checked = False
                try:
                    is_checked = cb.is_checked()
                except:
                    # If is_checked() fails, try clicking anyway
                    pass
                
                if not is_checked:
                    cb.click()
                    logger.debug(f"Checkbox clicked: {sel}")
                else:
                    logger.debug(f"Checkbox already checked: {sel}")
                
                checkbox_checked = True
                self.page.wait_for_timeout(800)
                break
            except PWTimeout:
                continue
        
        if not checkbox_checked:
            logger.warning("Could not find/check the checkbox — trying Start button anyway")

        # Click Start Contest button
        start_selectors = [
            "button:has-text('Start Contest')",
            "button:has-text('Start')",
            "a:has-text('Start Contest')",
            "[type='submit']:has-text('Start')",
        ]
        
        for sel in start_selectors:
            try:
                start = self.page.locator(sel).first
                start.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
                start.click()
                logger.info("Contest dialog confirmed ✅")
                self.page.wait_for_timeout(1_500)
                return True
            except PWTimeout:
                continue
        
        logger.error("'Start Contest' button not found")
        return False

    # ── 5. Return to BytsOne after LeetCode ────────────────────────────────────

    def return_to_problem_page(self) -> bool:
        """Navigate directly back to the saved BytsOne problem URL."""
        url = self._current_problem_url
        if not url or "bytsone.com" not in url:
            logger.warning("No saved BytsOne URL — re-opening course")
            return False
        logger.debug(f"Returning to BytsOne: {url}")
        self.page.goto(url)
        self.page.wait_for_load_state("load")
        self.page.wait_for_timeout(1_000)
        return True

    # ── 6. Completion ──────────────────────────────────────────────────────────

    def mark_complete(self) -> bool:
        """
        Click 'Mark as Complete', then confirm the 'Completion Verification' dialog
        that BytsOne shows ('Confirm Completion' button).
        """
        sel = BYTESONE_CHALLENGE["mark_complete_btn"]
        try:
            btn = self.page.locator(sel).first
            btn.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
            btn.click()
            logger.info("Clicked 'Mark as Complete' ✅")
            self.page.wait_for_timeout(1_500)
        except PWTimeout:
            logger.warning("'Mark as Complete' not found")
            return False

        # Handle the "Completion Verification" confirmation dialog
        confirm_selectors = [
            "button:has-text('Confirm Completion')",
            "button:has-text('Confirm')",
            "a:has-text('Confirm Completion')",
        ]
        for sel in confirm_selectors:
            try:
                confirm_btn = self.page.locator(sel).first
                confirm_btn.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
                confirm_btn.click()
                logger.info("Confirmed Completion dialog ✅")
                self.page.wait_for_timeout(1_000)
                return True
            except PWTimeout:
                continue

        # Dialog may not always appear (already confirmed or different state)
        logger.debug("No 'Confirm Completion' dialog — continuing")
        return True

    def click_next_lesson(self) -> bool:
        """Click 'Next Lesson'."""
        sel = BYTESONE_CHALLENGE["next_lesson_btn"]
        try:
            btn = self.page.locator(sel).first
            btn.wait_for(state="visible", timeout=TIMEOUT_SHORT)
            btn.click()
            self.page.wait_for_load_state("load")
            logger.debug("Next Lesson clicked")
            return True
        except PWTimeout:
            logger.debug("'Next Lesson' not found — likely last problem")
            return False
