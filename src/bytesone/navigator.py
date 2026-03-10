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
        self._chapter_url: Optional[str] = None           # course overview URL for stale-ref recovery

    # ── 1. Open course ─────────────────────────────────────────────────────────

    def open_course(self, course_key: str) -> bool:
        """Navigate to the course curriculum page. Returns True on success."""
        fragment = COURSE_TITLE_FRAGMENTS[course_key]
        logger.info(f"Opening course: {fragment}")

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

        # Find all course cards and filter by text match
        all_cards = self.page.locator("div").all()
        target_card = None
        
        for card in all_cards:
            try:
                text = card.inner_text(timeout=300).strip()
                # Match cards that contain our fragment but aren't giant ancestor divs
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

        return True

    # ── 2. Chapters ────────────────────────────────────────────────────────────

    def get_chapters(self) -> List[Dict]:
        """
        Chapter rows always contain a "%" (progress) or a lock icon.
        Use a scoped selector instead of scanning every element on the page.
        """
        self.page.wait_for_load_state("load")
        self.page.wait_for_timeout(2_000)  # give SPA time to render sidebar

        seen_days = set()
        chapters = []

        # Scope to elements whose text starts with "Day " — much faster than locator("*")
        candidates = self.page.locator("*:has-text('Day ')").all()
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
        """
        Click a day chapter to expand its problem list.
        Falls back to text-based re-discovery when the stored element is stale
        (e.g. after open_course reloads the page).
        """
        day_num = chapter["day_num"]
        label   = chapter["label"]

        def _try_element_click():
            chapter["element"].click()
            self.page.wait_for_load_state("load")
            self.page.wait_for_timeout(1_500)

        def _find_and_click_fresh():
            """Re-find the chapter sidebar row by 'Day N' text."""
            candidates = self.page.locator("*").filter(
                has_text=re.compile(rf"^Day\s+{day_num}\b")
            ).all()
            for el in candidates:
                try:
                    txt = el.inner_text(timeout=300).strip()
                    if re.match(rf"^Day\s+{day_num}\b", txt) and ("%" in txt or "lock" in el.inner_html(timeout=300).lower()):
                        el.click()
                        chapter["element"] = el   # refresh cached element
                        self.page.wait_for_load_state("load")
                        self.page.wait_for_timeout(1_500)
                        return True
                except Exception:
                    continue
            return False

        try:
            _try_element_click()
            self._chapter_url = self.page.url
            return True
        except Exception:
            logger.debug(f"Chapter element stale for {label} — re-finding in sidebar")
            try:
                ok = _find_and_click_fresh()
                if ok:
                    self._chapter_url = self.page.url
                return ok
            except Exception as e:
                logger.error(f"Could not click chapter {label}: {e}")
                return False

    # ── 3. Problems ────────────────────────────────────────────────────────────

    def get_problems_in_chapter(self, day_num: int) -> List[Dict]:
        """
        Find problems for the currently-selected chapter.
        Strategy 1 (primary): URL-based — find <a href> links to problem UUIDs.
        Strategy 2 (secondary): Sidebar-exclusion DOM scan — finds clickable items
                                  in the content panel by excluding sidebar cards.
        Strategy 3 (fallback): VLM screenshot — ask the model what problems are visible.
        """
        self.page.wait_for_timeout(1_500)

        # Strategy 1: UUID href links (works for most days)
        problems = self._get_problems_by_links()
        if problems:
            logger.info(
                f"Day {day_num} problems: "
                + ", ".join(f"{p['title']}({'✓' if p['completed'] else '○'})" for p in problems)
            )
            return problems

        logger.warning(f"[Day {day_num}] URL-based detection found nothing — trying DOM scan")

        # Strategy 2: sidebar-exclusion DOM scan (good for Day 1 which is the
        # default chapter and may render items without UUID-based hrefs)
        problems = self._get_problems_by_dom_scan(day_num)
        if problems:
            logger.info(
                f"Day {day_num} problems (DOM scan): "
                + ", ".join(f"{p['title']}({'✓' if p['completed'] else '○'})" for p in problems)
            )
            return problems

        logger.warning(f"[Day {day_num}] DOM scan found nothing — trying VLM screenshot")

        # Strategy 3: VLM screenshot
        problems = self._get_problems_via_vlm(day_num)
        if problems:
            logger.info(
                f"Day {day_num} problems (VLM): "
                + ", ".join(f"{p['title']}" for p in problems)
            )
            return problems

        logger.warning(f"[Day {day_num}] No problems found via any strategy — skipping")
        return []

    def _get_problems_by_links(self) -> List[Dict]:
        """
        Find problems by locating <a> tags whose href contains the course UUID
        followed by one or more additional UUIDs (problem/section identifiers).
        Handles both URL formats BytsOne uses:
          /home/course/{courseUuid}/active/{sectionUuid}
          /course/{courseUuid}/{moduleUuid}/{sectionUuid}/{problemUuid}
        """
        current_url = self.page.url
        m = re.search(r'(?:/home)?/course/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', current_url)
        if not m:
            logger.debug("_get_problems_by_links: not on a course page")
            return []
        course_uuid = m.group(1)

        # Non-problem navigation texts to skip
        JUNK_TITLES = {
            'toggle sidebar', 'bytsone', 'back', 'curriculum',
            'goal', 'analytics', 'leaderboard', 'certificate', 'communication channel',
            'chapters', 'select module', 'earn certificate', 'continue learning',
            'start learning', 'activate', 'log out', 'dashboard', 'explore',
            'assessments', 'schedule', 'live session', 'ide', 'resume builder',
            'notifications', 'settings', 'profile',
        }

        links_data = self.page.evaluate(
            r"""
            ([courseUuid, junkSet]) => {
                const UUID_PAT = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
                const UUID_RE  = new RegExp(UUID_PAT, 'i');
                // Match the course UUID with at least one more UUID in the path
                const COURSE_RE = new RegExp(
                    '(?:/home)?/course/' + courseUuid + '(?:/[^?#]+)?/' + UUID_PAT, 'i'
                );

                const results = [];
                const seenHref = new Set();
                const seenTitle = new Set();

                document.querySelectorAll('a[href]').forEach(a => {
                    const href = a.getAttribute('href') || '';
                    if (!COURSE_RE.test(href)) return;

                    // Must be a DEEPER link than the current chapter page
                    // i.e., it must have more path segments than just /active
                    const segments = href.split('/').filter(Boolean);
                    const uuidCount = segments.filter(s => UUID_RE.test(s)).length;
                    if (uuidCount < 2) return;  // need at least course uuid + problem uuid

                    if (seenHref.has(href)) return;
                    seenHref.add(href);

                    let title = (a.textContent || '').trim().replace(/[\n\r\t]+/g, ' ').replace(/\s+/g, ' ');
                    if (!title || title.length < 2 || title.length > 120) return;

                    // Skip day headers and lock messages
                    if (/^\d+\.?\s*Day\s+\d/i.test(title)) return;
                    if (/^Day\s+\d/i.test(title)) return;
                    if (/complete all previous/i.test(title)) return;
                    if (title.includes('%')) return;

                    const lower = title.toLowerCase();
                    if (junkSet.some(j => lower === j || lower.startsWith(j + ' '))) return;

                    if (seenTitle.has(lower)) return;
                    seenTitle.add(lower);

                    // Detect completion by checking for check/done/complete in the HTML
                    const html = a.innerHTML || '';
                    const done = /check|done|complete/i.test(html);

                    results.push({ title, href, completed: done });
                });

                return results;
            }
            """,
            [course_uuid, list(JUNK_TITLES)],
        )

        if not links_data:
            return []

        problems = []
        for p in links_data:
            title = p["title"].strip()
            if not title:
                continue
            href = p["href"]
            problems.append({
                "title":      title,
                "problem_id": _slugify(title),
                "completed":  p["completed"],
                "href":       href,
                "element":    self.page.locator(f'a[href="{href}"]').first,
            })
        return problems

    def _get_problems_by_dom_scan(self, day_num: int) -> List[Dict]:
        """
        Fallback problem detector.  Scopes to the RIGHT content panel by looking
        for the numbered Day heading ("1. Day 1") which only appears in the main
        content — not in the left sidebar (which uses "DAY 1" in caps).
        Applies very strict text filters so only proper LeetCode-style problem
        titles make it through.
        """
        scan_data = self.page.evaluate(
            r"""
            (dayNum) => {
                // ── exhaustive junk-skip list ─────────────────────────────────
                const SKIP_EXACT = new Set([
                    'dashboard','overall report','assessments','contest calendar',
                    'mentoring support','global platform assessments','courses',
                    'dsa sheets','explore','certificates','live session','ide',
                    'ai interview','ai interview (new)','resume builder',
                    'gps leaderboard','log out','back','completed','schedule',
                    'notifications','settings','profile','leaderboard',
                    'complete all previous chapters to proceed',
                    'curriculum','goal','analytics','certificate',
                    'communication channel','chapters','select module',
                    'earn certificate','toggle sidebar','bytsone',
                    'continue learning','start learning','activate',
                    'take challenge','start contest','mark as complete',
                    'next lesson','previous','report issue',
                ]);
                const SKIP_PREFIX = [
                    'day ', 'toggle', 'karunya', 'course content',
                ];
                const SKIP_CONTAINS = [
                    '%', '(', 'certificate available', 'product fit',
                    '9-3-2026', '13-3-2026', '16-2-2026', '21-2-2026',
                    'earn certificate', 'chapters', 'time spent',
                    'challenge incomplete', 'active since',
                ];

                // ── find the RIGHT content panel ──────────────────────────────
                // The right panel has a numbered heading like "1. Day N" or just
                // shows the problem list directly.  The left sidebar uses allcaps.
                let contentRoot = null;

                // Option A: find a heading that matches "N. Day M" pattern
                const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5'));
                for (const h of headings) {
                    const t = (h.textContent || '').trim();
                    if (/^\d+\.\s*Day\s+\d+/i.test(t)) {
                        // Walk up to a reasonable container
                        let node = h.parentElement;
                        for (let i = 0; i < 6 && node && node !== document.body; i++) {
                            if (node.children.length > 2) { contentRoot = node; break; }
                            node = node.parentElement;
                        }
                        if (!contentRoot) contentRoot = h.parentElement;
                        break;
                    }
                }

                // Option B: fallback — use main/article/section or a large div
                if (!contentRoot) {
                    contentRoot = document.querySelector('main,article,section,[role="main"]')
                                  || document.body;
                }

                // ── collect candidates from the content root ───────────────────
                const results = [];
                const seen = new Set();

                // Check ALL descendants — problem rows can be divs or li
                const candidates = Array.from(contentRoot.querySelectorAll('li,div,span,p'));

                for (const el of candidates) {
                    // Skip elements with many children — they are container rows
                    if (el.children.length > 3) continue;

                    const raw = (el.textContent || '').trim()
                        .replace(/[\n\r\t]+/g, ' ')
                        .replace(/\s+/g, ' ');

                    if (!raw || raw.length < 3 || raw.length > 60) continue;

                    const lower = raw.toLowerCase();

                    if (SKIP_EXACT.has(lower)) continue;
                    if (SKIP_PREFIX.some(p => lower.startsWith(p))) continue;
                    if (SKIP_CONTAINS.some(p => lower.includes(p))) continue;

                    // Must look like a problem title: 1-6 words, each word capitalised
                    // (LeetCode titles are Title Case)
                    const words = raw.split(' ');
                    if (words.length < 1 || words.length > 8) continue;
                    // At least the first word must start with a letter (not a digit)
                    if (!/^[A-Za-z]/.test(raw)) continue;

                    if (seen.has(raw)) continue;
                    seen.add(raw);

                    const html = el.innerHTML || '';
                    const done = /check|done|complete/i.test(html);

                    // Record a stable CSS selector path so we can re-find the element
                    // without relying on text matching (which hits sidebar too).
                    results.push({ title: raw, completed: done });
                }

                return results;
            }
            """,
            day_num,
        )

        if not scan_data:
            return []

        problems = []
        for p in scan_data:
            title = p["title"].strip()
            if not title:
                continue
            # Use a scoped locator: prefer items inside the problem-list area
            # by anchoring to an element that contains ANY text equal to the title
            # AND is not the sidebar chapter row (sidebar items tend to be preceded
            # by "DAY" in all-caps just above them).
            element = self.page.locator(
                "li, div, span"
            ).filter(has_text=re.compile(r"^" + re.escape(title) + r"$")).first

            problems.append({
                "title":      title,
                "problem_id": _slugify(title),
                "completed":  p["completed"],
                "href":       None,
                "element":    element,
            })
        return problems

    def _get_problems_via_vlm(self, day_num: int) -> List[Dict]:
        """
        Take a page screenshot and ask the VLM to identify the problem titles
        visible in the content area. Used when DOM-based detection fails.
        """
        import json
        from src.ai.solver import AIAgent

        try:
            screenshot = self.page.screenshot()
            question = (
                f"This is a screenshot of an online coding platform. "
                f"Day {day_num} is currently selected in the left sidebar. "
                f"Look ONLY at the main content panel (right side), NOT the left sidebar. "
                f"List the coding problem titles shown in that content area. "
                f"Return ONLY a JSON array of strings, e.g.: "
                f'["Two Sum", "Reverse String"]. '
                f"If no problems are visible, return an empty array []."
            )
            agent = AIAgent()
            response = agent.analyze_page(screenshot, question)
            if not response:
                return []

            # Extract JSON array from response
            match = re.search(r'\[.*?\]', response, re.DOTALL)
            if not match:
                logger.warning(f"[VLM] Could not parse JSON from response: {response[:200]}")
                return []

            titles = json.loads(match.group())
            if not isinstance(titles, list):
                return []

            problems = []
            for title in titles:
                if not isinstance(title, str) or not title.strip():
                    continue
                t = title.strip()
                problems.append({
                    "title":      t,
                    "problem_id": _slugify(t),
                    "completed":  False,
                    "href":       None,
                    "element":    self.page.locator("li, div, span").filter(
                                      has_text=re.compile(r"^" + re.escape(t) + r"$")
                                  ).first,
                })
            return problems

        except Exception as e:
            logger.error(f"[VLM] Screenshot analysis failed: {e}")
            return []

    def click_problem(self, problem: Dict) -> bool:
        """
        Open a problem detail page.
        - If we have an href (from link-based detection), navigate directly.
        - Otherwise, return to the chapter overview page first so element refs
          are fresh, then click.
        Validates the resulting URL has ≥2 UUIDs to confirm it's a problem page.
        """
        self._current_problem_url = self.page.url
        href = problem.get("href")

        try:
            if href:
                # Direct navigation — most reliable
                full_url = href if href.startswith("http") else f"https://www.bytsone.com{href}"
                self.page.goto(full_url)
            else:
                # For DOM-scan elements, ensure we're on the chapter overview page
                # so element references are valid (not stale)
                if self._chapter_url and self.page.url != self._chapter_url:
                    logger.debug(f"Re-navigating to chapter page for fresh element: {self._chapter_url}")
                    self.page.goto(self._chapter_url)
                    self.page.wait_for_load_state("load")
                    self.page.wait_for_timeout(1_500)
                    # Re-find the element on the refreshed page
                    title = problem["title"]
                    problem["element"] = self.page.locator(
                        "li, div, span"
                    ).filter(has_text=re.compile(r"^" + re.escape(title) + r"$")).first

                problem["element"].click()

            self.page.wait_for_load_state("load")
            self.page.wait_for_timeout(2_500)
            final_url = self.page.url
            logger.info(f"Opened problem: {problem['title']}  URL: {final_url}")

            # Must land on a course problem page (has /course/ in URL with ≥2 UUIDs)
            if "bytsone.com" not in final_url:
                logger.error(f"Navigated away from BytsOne: {final_url}")
                self.page.go_back()
                self.page.wait_for_load_state("load")
                return False

            uuid_count = len(re.findall(
                r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
                final_url, re.I
            ))
            if uuid_count < 2:
                logger.error(
                    f"URL doesn't look like a problem page ({uuid_count} UUID): {final_url}"
                )
                self.page.go_back()
                self.page.wait_for_load_state("load")
                return False

            self._current_problem_url = final_url   # update to actual deep URL
            return True

        except Exception as e:
            logger.error(f"Could not open problem '{problem['title']}': {e}")
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

        # Scroll down to ensure the button is in view (some pages hide it below fold)
        try:
            self.page.evaluate("window.scrollBy(0, 300)")
            self.page.wait_for_timeout(500)
        except Exception:
            pass

        # Try multiple button text variants — BytsOne uses different labels per course
        challenge_selectors = [
            "button:has-text('Take Challenge')",
            "a:has-text('Take Challenge')",
            "button:has-text('Start Challenge')",
            "a:has-text('Start Challenge')",
            "button:has-text('Go to Challenge')",
            "button:has-text('Solve')",
        ]

        for sel in challenge_selectors:
            try:
                btn = self.page.locator(sel).first
                btn.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
                btn.click()
                logger.info(f"Clicked 'Take Challenge' (selector: {sel})")
                self.page.wait_for_timeout(1_500)
                return True
            except PWTimeout:
                continue

        # Last resort: dump visible buttons to help diagnose
        try:
            btn_texts = self.page.evaluate(
                "() => Array.from(document.querySelectorAll('button,a')).map(b => b.textContent.trim()).filter(t => t && t.length < 50)"
            )
            logger.error(f"'Take Challenge' button not found. Visible buttons/links: {btn_texts[:20]}")
        except Exception:
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
        """Click 'Mark as Complete', then confirm the Completion Verification dialog."""
        sel = BYTESONE_CHALLENGE["mark_complete_btn"]
        try:
            btn = self.page.locator(sel).first
            btn.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
            btn.click()
            logger.info("Clicked 'Mark as Complete'")
            self.page.wait_for_timeout(1_500)
        except PWTimeout:
            logger.warning("'Mark as Complete' not found")
            return False

        # Handle the "Completion Verification" confirmation dialog
        confirm_selectors = [
            "button:has-text('Confirm Completion')",
            "button:has-text('Confirm')",
            "a:has-text('Confirm Completion')",
            "[role='dialog'] button:has-text('Confirm')",
        ]
        for sel in confirm_selectors:
            try:
                confirm_btn = self.page.locator(sel).first
                confirm_btn.wait_for(state="visible", timeout=TIMEOUT_SHORT)
                confirm_btn.click()
                logger.info("Marked as Complete ✅")
                self.page.wait_for_timeout(1_000)
                return True
            except PWTimeout:
                continue

        # No confirmation dialog — treat original click as success
        logger.info("Marked as Complete ✅ (no confirmation dialog)")
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
