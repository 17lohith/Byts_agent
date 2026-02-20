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

    # ── 1. Open course ─────────────────────────────────────────────────────────

    def open_course(self, course_key: str) -> bool:
        """Navigate to the course curriculum page. Returns True on success."""
        fragment = COURSE_TITLE_FRAGMENTS[course_key]
        logger.info(f"Opening course: {fragment}")

        self.page.goto(BYTESONE_COURSES_URL)
        self.page.wait_for_load_state("networkidle")

        # Find all course cards and filter by exact text match to avoid ancestor issues
        all_cards = self.page.locator("div").all()
        target_card = None
        
        for card in all_cards:
            try:
                text = card.inner_text(timeout=300).strip()
                # Check if this div contains ONLY our course title (not parent container)
                if fragment in text and len(text) < len(fragment) + 100:
                    target_card = card
                    break
            except Exception:
                continue
        
        if target_card is None:
            logger.error(f"Course card not found: {fragment}")
            return False

        # Click "Continue Learning" scoped to that card
        clicked = False
        for btn_text in ["Continue Learning"]:
            try:
                # Find button within the card element
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

        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2_000)
        final_url = self.page.url
        logger.info(f"Opened course: {fragment} ✅  URL: {final_url}")

        # Verify we landed on a course page (not still on courses list)
        if "/home/course/" not in final_url and "/home/courses" in final_url:
            logger.error(f"Navigation failed — still on courses page: {final_url}")
            return False

        return True

    # ── 2. Chapters ────────────────────────────────────────────────────────────

    def get_chapters(self) -> List[Dict]:
        """
        KEY INSIGHT: Chapter rows always contain a "%" (progress) or a lock icon.
        Global nav items (Dashboard, Overall Report…) NEVER contain "%".
        So we filter on that to get only the real Day 1-6 entries.
        """
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1_500)

        seen_days = set()
        chapters = []

        # Get all elements that start with "Day N" text
        candidates = self.page.locator("*").all()
        for el in candidates:
            try:
                text = el.inner_text(timeout=300).strip()
            except Exception:
                continue

            # Must start with "Day <digit>"
            m = re.match(r"^Day\s+(\d+)", text)
            if not m:
                continue

            day_num = int(m.group(1))
            if day_num < 1 or day_num > 6 or day_num in seen_days:
                continue

            # FILTER: must have "%" (progress indicator) or "lock" (lock icon)
            has_pct  = "%" in text
            has_lock = False
            try:
                inner_html = el.inner_html(timeout=300)
                has_lock = "lock" in inner_html.lower() or "🔒" in text
            except Exception:
                pass

            if not has_pct and not has_lock:
                continue  # skip global nav items

            # Parse progress
            pct = 0
            m_pct = re.search(r"(\d+)%", text)
            if m_pct:
                pct = int(m_pct.group(1))

            seen_days.add(day_num)
            chapters.append({
                "label":        f"Day {day_num}",
                "day_num":      day_num,
                "locked":       has_lock and not has_pct,
                "completed":    pct == 100,
                "progress_pct": pct,
                "element":      el,
            })

        chapters.sort(key=lambda c: c["day_num"])
        logger.info(
            f"Chapters found: "
            + ", ".join(f"{c['label']}({c['progress_pct']}%{'🔒' if c['locked'] else ''})" for c in chapters)
        )
        return chapters

    def click_chapter(self, chapter: Dict) -> bool:
        """Click a day chapter. Returns True on success."""
        try:
            chapter["element"].click()
            self.page.wait_for_load_state("networkidle")
            self.page.wait_for_timeout(1_500)
            return True
        except Exception as e:
            logger.error(f"Could not click chapter {chapter['label']}: {e}")
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
                    'completed',  // Filter out the "Completed" status item
                ]);

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
            "gps leaderboard", "log out", "back", "completed",
        }
        results = []
        seen = set()
        for li in self.page.locator("li").all():
            try:
                t = li.inner_text().strip()
                if not t or t.lower() in _NAV or re.match(r"^Day\s+\d", t) or "%" in t:
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
        """Click a problem row. Saves the current URL before navigating."""
        self._current_problem_url = self.page.url
        try:
            problem["element"].click()
            self.page.wait_for_load_state("networkidle")
            self.page.wait_for_timeout(1_000)
            logger.debug(f"Opened problem: {problem['title']}  URL: {self.page.url}")
            return True
        except Exception as e:
            logger.error(f"Could not click problem '{problem['title']}': {e}")
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
        """Click the 'Take Challenge' button. Saves URL so we can return later."""
        self._current_problem_url = self.page.url   # save for return trip
        sel = BYTESONE_CHALLENGE["take_challenge"]
        try:
            btn = self.page.locator(sel).first
            btn.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
            btn.click()
            logger.info("Clicked 'Take Challenge'")
            self.page.wait_for_timeout(1_500)
            return True
        except PWTimeout:
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
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1_000)
        return True

    # ── 6. Completion ──────────────────────────────────────────────────────────

    def mark_complete(self) -> bool:
        """Click 'Mark as Complete'."""
        sel = BYTESONE_CHALLENGE["mark_complete_btn"]
        try:
            btn = self.page.locator(sel).first
            btn.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
            btn.click()
            logger.info("Marked as Complete ✅")
            self.page.wait_for_timeout(1_000)
            return True
        except PWTimeout:
            logger.warning("'Mark as Complete' not found")
            return False

    def click_next_lesson(self) -> bool:
        """Click 'Next Lesson'."""
        sel = BYTESONE_CHALLENGE["next_lesson_btn"]
        try:
            btn = self.page.locator(sel).first
            btn.wait_for(state="visible", timeout=TIMEOUT_SHORT)
            btn.click()
            self.page.wait_for_load_state("networkidle")
            logger.debug("Next Lesson clicked")
            return True
        except PWTimeout:
            logger.debug("'Next Lesson' not found — likely last problem")
            return False
