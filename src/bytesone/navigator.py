"""BytsOne navigator — courses → chapters → problems → Take Challenge → Mark Complete."""

import time
import re
from typing import List, Dict, Optional
from playwright.sync_api import Page, TimeoutError as PWTimeout

from src.config.constants import (
    BYTESONE_COURSES, BYTESONE_CHALLENGE, COURSE_TITLE_FRAGMENTS,
    BYTESONE_COURSES_URL, TIMEOUT_SHORT, TIMEOUT_MEDIUM, TIMEOUT_LONG,
)
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# Known BytsOne global nav items — used to EXCLUDE them from problem lists
_NAV_ITEMS = {
    "dashboard", "overall report", "assessments", "contest calendar",
    "mentoring support", "global platform assessments", "courses",
    "dsa sheets", "explore", "certificates", "live session", "ide",
    "ai interview", "ai interview (new)", "resume builder",
    "gps leaderboard", "log out", "back",
}


class BytesOneNavigator:
    def __init__(self, page: Page):
        from src.config.settings import settings
        self.page = page
        self.settings = settings

    # ── 1. Courses page ────────────────────────────────────────────────────────

    def go_to_courses(self):
        self.page.goto(BYTESONE_COURSES_URL)
        self.page.wait_for_load_state("networkidle")

    def open_course(self, course_key: str) -> bool:
        """
        Navigate to the course overview page.
        Returns True when the course page is loaded.
        """
        fragment = COURSE_TITLE_FRAGMENTS[course_key]
        logger.info(f"Opening course: {fragment}")
        self.go_to_courses()

        # Find the course card
        try:
            card_text = self.page.locator(f"text={fragment}").first
            card_text.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
        except PWTimeout:
            logger.error(f"Course card not found: {fragment}")
            return False

        # Find and click Continue Learning inside the same card
        # Scope to a container that has this fragment text
        try:
            # Walk up to card container
            btn = self.page.locator(
                f"div:has-text('{fragment}') >> button:has-text('Continue Learning')"
            ).first
            btn.wait_for(state="visible", timeout=TIMEOUT_SHORT)
            btn.click()
        except PWTimeout:
            try:
                btn = self.page.locator(
                    f"div:has-text('{fragment}') >> a:has-text('Continue Learning')"
                ).first
                btn.wait_for(state="visible", timeout=TIMEOUT_SHORT)
                btn.click()
            except PWTimeout:
                # Fallback: just click the card title itself
                card_text.click()

        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1_500)
        logger.info(f"Opened course: {fragment} ✅")
        return True

    # ── 2. Chapter list ────────────────────────────────────────────────────────

    def get_chapters(self) -> List[Dict]:
        """
        Use JavaScript to find the 'Chapters' section and extract Day 1-6 data.
        Returns list of {label, day_num, locked, completed, progress_pct, element}.
        """
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1_500)

        # Use JavaScript to locate the chapters container based on having
        # "Chapters" as a header text within the page content area.
        chapters_data = self.page.evaluate("""
        () => {
            // Find the "Chapters" heading (not global nav, specifically course chapters)
            const allEls = Array.from(document.querySelectorAll('*'));

            // Find element whose DIRECT text is exactly "Chapters"
            let chaptersHeading = null;
            for (const el of allEls) {
                const direct = Array.from(el.childNodes)
                    .filter(n => n.nodeType === 3)
                    .map(n => n.textContent.trim())
                    .join('');
                if (direct === 'Chapters') {
                    chaptersHeading = el;
                    break;
                }
            }

            if (!chaptersHeading) return { found: false, container_html: '' };

            // Walk UP to find a container that has multiple "Day N" items
            let container = chaptersHeading.parentElement;
            for (let i = 0; i < 6; i++) {
                if (!container) break;
                const dayItems = Array.from(container.querySelectorAll('*'))
                    .filter(el => /^Day\\s+\\d/.test(el.textContent.trim().slice(0, 8)));
                if (dayItems.length >= 2) break;
                container = container.parentElement;
            }

            // Extract unique day entries
            if (!container) return { found: false, container_html: '' };

            const seen = new Set();
            const days = [];

            // Find elements whose text STARTS WITH "Day N"
            const candidates = Array.from(container.querySelectorAll('li, div'))
                .filter(el => {
                    const t = el.textContent.trim();
                    return /^Day\\s+\\d/.test(t.slice(0, 8));
                });

            for (const el of candidates) {
                const text = el.textContent.trim();
                const m = text.match(/Day\\s+(\\d+)/);
                if (!m) continue;
                const dayNum = parseInt(m[1]);
                if (seen.has(dayNum)) continue;
                seen.add(dayNum);

                // Check locked (look for lock emoji or SVG with lock path)
                const locked = el.innerHTML.includes('lock') ||
                               el.textContent.includes('🔒') ||
                               el.querySelector('[data-icon="lock"]') !== null;

                // Extract progress percentage
                let pct = 0;
                const pctMatch = text.match(/(\\d+)%/);
                if (pctMatch) pct = parseInt(pctMatch[1]);

                days.push({ dayNum, text: text.slice(0, 60), locked, pct });
            }

            return { found: true, days };
        }
        """)

        if not chapters_data.get("found") or not chapters_data.get("days"):
            logger.error("Could not find 'Chapters' section via JS — falling back to locators")
            return self._get_chapters_fallback()

        chapters = []
        for d in chapters_data["days"]:
            day_num = d["dayNum"]
            label = f"Day {day_num}"

            # Get a Playwright locator for this specific day row
            # Use the exact label text to scope, then narrow
            element = self._locate_chapter_element(day_num)

            chapters.append({
                "label": label,
                "day_num": day_num,
                "locked": d["locked"],
                "completed": d["pct"] == 100,
                "progress_pct": d["pct"],
                "element": element,
            })

        chapters.sort(key=lambda c: c["day_num"])
        logger.info(f"Found {len(chapters)} chapter(s): {[c['label'] for c in chapters]}")
        return chapters

    def _locate_chapter_element(self, day_num: int):
        """Return a Playwright locator for the chapter row, scoped away from global nav."""
        # Try precise text match first
        for sel in [
            f"li:has-text('Day {day_num}')",
            f"div:has-text('Day {day_num}')",
        ]:
            locs = self.page.locator(sel).all()
            # Filter to elements that also contain a "%" (progress) or lock icon
            for loc in locs:
                try:
                    t = loc.inner_text(timeout=500)
                    # Must start with "Day N" and ideally have % or lock
                    if re.match(rf"^Day\s+{day_num}", t.strip()):
                        return loc
                except Exception:
                    continue

        # Final fallback: just first match
        return self.page.locator(f"text=Day {day_num}").first

    def _get_chapters_fallback(self) -> List[Dict]:
        """Fallback: find Day rows by text, deduplicate, filter out nav items."""
        rows = self.page.locator("li:has-text('Day'), div:has-text('Day')").all()
        seen = set()
        chapters = []
        for row in rows:
            try:
                text = row.inner_text().strip()
                m = re.match(r"^Day\s+(\d+)", text)
                if not m:
                    continue
                day_num = int(m.group(1))
                if day_num in seen or day_num > 6:
                    continue
                seen.add(day_num)
                chapters.append({
                    "label": f"Day {day_num}",
                    "day_num": day_num,
                    "locked": "lock" in row.inner_html().lower(),
                    "completed": "100%" in text,
                    "progress_pct": 0,
                    "element": row,
                })
            except Exception:
                continue
        chapters.sort(key=lambda c: c["day_num"])
        return chapters

    def click_chapter(self, chapter: Dict) -> bool:
        """Click a chapter row to load its problem list."""
        try:
            chapter["element"].click()
            self.page.wait_for_load_state("networkidle")
            self.page.wait_for_timeout(1_500)
            return True
        except Exception as e:
            logger.error(f"Could not click chapter {chapter['label']}: {e}")
            return False

    # ── 3. Problem list (inside a chapter) ────────────────────────────────────

    def get_problems_in_chapter(self, day_num: int) -> List[Dict]:
        """
        After clicking a chapter, parse the problem list shown in the right panel.
        Uses JavaScript to find the content panel (not the global nav).
        Returns list of {title, problem_id, completed, element}.
        """
        self.page.wait_for_timeout(1_500)

        # Use JavaScript to find the problems panel for the currently selected day
        problems_data = self.page.evaluate(f"""
        () => {{
            // The right content panel should have a "Day {day_num}" heading
            // and a list of problems below it.
            // Strategy: find elements that look like problem rows (NOT nav items)

            const navItems = new Set([
                'dashboard', 'overall report', 'assessments', 'contest calendar',
                'mentoring support', 'global platform assessments', 'courses',
                'dsa sheets', 'explore', 'certificates', 'live session', 'ide',
                'ai interview', 'ai interview (new)', 'resume builder',
                'gps leaderboard', 'log out', 'back'
            ]);

            // Find the Day {day_num} heading in the content area
            const dayHeadings = Array.from(document.querySelectorAll('h1, h2, h3, h4, div'))
                .filter(el => {{
                    const t = el.textContent.trim();
                    return t.startsWith('{day_num}. Day {day_num}') ||
                           t === 'Day {day_num}' ||
                           t.startsWith('Day {day_num}\\n');
                }});

            if (dayHeadings.length === 0) return {{ found: false }};

            // Take the last one (rightmost / content area)
            const heading = dayHeadings[dayHeadings.length - 1];

            // Find the container that holds the problems list
            // Walk up to find a container that has multiple children
            let container = heading.parentElement;
            for (let i = 0; i < 5; i++) {{
                if (!container) break;
                const children = Array.from(container.children);
                if (children.length >= 3) break;
                container = container.parentElement;
            }}

            if (!container) return {{ found: false }};

            // Find all text items in this container that are not nav items
            const items = [];
            const seen = new Set();

            Array.from(container.querySelectorAll('li, a, span, div'))
                .forEach(el => {{
                    // Only direct-ish children (max 4 levels deep from container)
                    let depth = 0, p = el.parentElement;
                    while (p && p !== container) {{ depth++; p = p.parentElement; }}
                    if (depth > 4) return;

                    const text = el.textContent.trim().replace(/\\n/g, ' ').replace(/\\s+/g, ' ');
                    if (!text || text.length < 2 || text.length > 120) return;
                    if (navItems.has(text.toLowerCase())) return;
                    if (/^Day\\s+\\d/.test(text)) return; // skip day headers
                    if (/^\\d+%/.test(text) || text === 'Completed') return; // skip labels
                    if (seen.has(text)) return;
                    seen.add(text);

                    const completed = el.innerHTML.includes('check') ||
                                     el.classList.toString().includes('complete') ||
                                     el.querySelector('[class*="check"]') !== null;

                    items.push({{ text, completed }});
                }});

            return {{ found: true, items }};
        }}
        """)

        if not problems_data.get("found"):
            logger.warning(f"JS problem extraction failed for Day {day_num} — trying CSS fallback")
            return self._get_problems_fallback(day_num)

        items = problems_data.get("items", [])
        problems = []
        for item in items:
            title = item["text"].strip()
            if not title:
                continue
            problem_id = re.sub(r"[^a-z0-9\s-]", "", title.lower())
            problem_id = re.sub(r"\s+", "-", problem_id).strip("-")
            problems.append({
                "title": title,
                "problem_id": problem_id,
                "completed": item["completed"],
                "element": self.page.locator(f"text={title}").first,
            })

        logger.info(f"Found {len(problems)} problem(s) in Day {day_num}")
        return problems

    def _get_problems_fallback(self, day_num: int) -> List[Dict]:
        """Fallback: get all visible text items and filter out nav items."""
        day_header_locs = self.page.locator(
            f"h1:has-text('Day {day_num}'), h2:has-text('Day {day_num}'), "
            f"h3:has-text('Day {day_num}'), div:has-text('{day_num}. Day {day_num}')"
        ).all()

        if not day_header_locs:
            return []

        # Use the last heading (content area, not sidebar)
        header = day_header_locs[-1]

        # Get sibling/following elements that are problems
        problems = []
        candidate_locs = self.page.locator("li, a[class*='lesson'], a[class*='problem']").all()
        for loc in candidate_locs:
            try:
                text = loc.inner_text().strip()
                if not text or text.lower() in _NAV_ITEMS:
                    continue
                if re.match(r"^Day\s+\d", text):
                    continue
                problem_id = re.sub(r"[^a-z0-9\s-]", "", text.lower())
                problem_id = re.sub(r"\s+", "-", problem_id).strip("-")
                problems.append({
                    "title": text,
                    "problem_id": problem_id,
                    "completed": False,
                    "element": loc,
                })
            except Exception:
                continue
        return problems

    def click_problem(self, problem: Dict) -> bool:
        """Click a problem to open its detail page."""
        try:
            problem["element"].click()
            self.page.wait_for_load_state("networkidle")
            self.page.wait_for_timeout(1_000)
            return True
        except Exception as e:
            logger.error(f"Could not click problem '{problem['title']}': {e}")
            return False

    # ── 4. Problem detail: Take Challenge ─────────────────────────────────────

    def click_take_challenge(self) -> bool:
        """Click the 'Take Challenge' button on the problem detail page."""
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
        Handle the two-step LeetCode Contest confirmation dialog:
          Step 1: username shown + "Continue" button
          Step 2: checkbox + "Start Contest" button
        """
        # Step 1 — "Continue" button
        try:
            btn = self.page.locator(BYTESONE_CHALLENGE["dialog_continue_btn"]).first
            btn.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
            btn.click()
            logger.debug("Dialog step 1: clicked Continue")
            self.page.wait_for_timeout(1_000)
        except PWTimeout:
            logger.debug("No 'Continue' dialog — skipping to step 2")

        # Step 2 — checkbox + "Start Contest"
        try:
            checkbox = self.page.locator(BYTESONE_CHALLENGE["dialog_checkbox"]).first
            checkbox.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
            if not checkbox.is_checked():
                checkbox.check()
            self.page.wait_for_timeout(500)

            start_btn = self.page.locator(BYTESONE_CHALLENGE["dialog_start_btn"]).first
            start_btn.wait_for(state="visible", timeout=TIMEOUT_SHORT)
            start_btn.click()
            logger.info("Dialog: clicked 'Start Contest' ✅")
            return True
        except PWTimeout:
            logger.error("'Start Contest' button not found in dialog")
            return False

    # ── 5. Completion ──────────────────────────────────────────────────────────

    def mark_complete(self) -> bool:
        """Click 'Mark as Complete' on the current problem page."""
        sel = BYTESONE_CHALLENGE["mark_complete_btn"]
        try:
            btn = self.page.locator(sel).first
            btn.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
            btn.click()
            logger.info("Clicked 'Mark as Complete' ✅")
            self.page.wait_for_timeout(1_000)
            return True
        except PWTimeout:
            logger.warning("'Mark as Complete' button not found")
            return False

    def click_next_lesson(self) -> bool:
        """Click 'Next Lesson' to advance."""
        sel = BYTESONE_CHALLENGE["next_lesson_btn"]
        try:
            btn = self.page.locator(sel).first
            btn.wait_for(state="visible", timeout=TIMEOUT_SHORT)
            btn.click()
            self.page.wait_for_load_state("networkidle")
            logger.debug("Clicked 'Next Lesson'")
            return True
        except PWTimeout:
            logger.debug("'Next Lesson' not found — may be last problem")
            return False

    def get_current_url(self) -> str:
        return self.page.url
