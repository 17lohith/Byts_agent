"""BytsOne navigator — courses → chapters → problems → Take Challenge → Mark Complete."""

import time
from typing import List, Dict, Optional
from playwright.sync_api import Page, TimeoutError as PWTimeout

from src.config.constants import (
    BYTESONE_COURSES, BYTESONE_CHAPTER, BYTESONE_PROBLEM,
    BYTESONE_CHALLENGE, COURSE_TITLE_FRAGMENTS,
    BYTESONE_COURSES_URL, TIMEOUT_SHORT, TIMEOUT_MEDIUM, TIMEOUT_LONG,
)
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class BytesOneNavigator:
    def __init__(self, page: Page):
        from src.config.settings import settings
        self.page = page
        self.settings = settings

    # ── 1. Courses page ────────────────────────────────────────────────────────

    def go_to_courses(self):
        """Navigate to the BytsOne Courses page."""
        logger.info("Navigating to Courses page …")
        self.page.goto(BYTESONE_COURSES_URL)
        self.page.wait_for_load_state("networkidle")

    def open_course(self, course_key: str) -> bool:
        """
        Click the correct course card and enter the curriculum view.
        course_key: 'class_problems' or 'task_problems'
        Returns True on success.
        """
        fragment = COURSE_TITLE_FRAGMENTS[course_key]
        logger.info(f"Opening course: {fragment}")
        self.go_to_courses()

        # Find the card containing this fragment
        try:
            card = self.page.locator(f"text={fragment}").first
            card.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
        except PWTimeout:
            logger.error(f"Course card not found for: {fragment}")
            return False

        # Click "Continue Learning" inside that card
        try:
            # Find the card container and click its Continue Learning button
            card_container = self.page.locator(
                f"[class*='card']:has-text('{fragment}'), "
                f"[class*='course']:has-text('{fragment}'), "
                f"div:has-text('{fragment}')"
            ).first
            btn = card_container.locator(
                "button:has-text('Continue Learning'), a:has-text('Continue Learning')"
            ).first
            btn.wait_for(state="visible", timeout=TIMEOUT_SHORT)
            btn.click()
        except PWTimeout:
            # Fallback: click the title text itself
            logger.warning("Could not find Continue Learning button — clicking card title")
            card.click()

        self.page.wait_for_load_state("networkidle")
        logger.info(f"Opened course: {fragment} ✅")
        return True

    # ── 2. Chapter list ────────────────────────────────────────────────────────

    def get_chapters(self) -> List[Dict]:
        """
        Parse the chapter sidebar and return list of:
        {
          "label": "Day 1",
          "day_num": 1,
          "locked": False,
          "completed": False,
          "progress_pct": 100,
          "element": <Locator>
        }
        """
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1_500)

        chapters = []

        # Try common chapter/day list selectors
        selectors_to_try = [
            "li:has-text('Day')",
            "[class*='chapter']:has-text('Day')",
            "[class*='Chapter']:has-text('Day')",
            "div:has-text('Day 1')",
        ]

        rows = []
        for sel in selectors_to_try:
            rows = self.page.locator(sel).all()
            if rows:
                logger.debug(f"Chapter selector matched: {sel} ({len(rows)} rows)")
                break

        if not rows:
            logger.error("No chapter rows found on page")
            return chapters

        for row in rows:
            try:
                text = row.inner_text().strip()
                # Must contain "Day" followed by a number
                if "Day" not in text:
                    continue

                # Extract day number
                day_num = None
                for part in text.split():
                    if part.isdigit():
                        day_num = int(part)
                        break
                if day_num is None:
                    continue

                # Check locked
                locked = False
                try:
                    row.locator(BYTESONE_CHAPTER["lock_icon"]).wait_for(timeout=500)
                    locked = True
                except PWTimeout:
                    pass

                # Extract progress percentage
                progress_pct = 0
                if "100%" in text:
                    progress_pct = 100
                elif "%" in text:
                    for part in text.split():
                        if "%" in part:
                            try:
                                progress_pct = int(part.replace("%", ""))
                            except ValueError:
                                pass

                completed = progress_pct == 100

                chapters.append({
                    "label": f"Day {day_num}",
                    "day_num": day_num,
                    "locked": locked,
                    "completed": completed,
                    "progress_pct": progress_pct,
                    "element": row,
                })

            except Exception as e:
                logger.debug(f"Skipped chapter row: {e}")
                continue

        chapters.sort(key=lambda c: c["day_num"])
        logger.info(f"Found {len(chapters)} chapter(s)")
        return chapters

    def click_chapter(self, chapter: Dict) -> bool:
        """Click a chapter row to load its problem list."""
        try:
            chapter["element"].click()
            self.page.wait_for_load_state("networkidle")
            self.page.wait_for_timeout(1_000)
            return True
        except Exception as e:
            logger.error(f"Could not click chapter {chapter['label']}: {e}")
            return False

    # ── 3. Problem list (inside a chapter) ────────────────────────────────────

    def get_problems_in_chapter(self) -> List[Dict]:
        """
        Parse problems listed in the right panel after clicking a chapter.
        Returns list of:
        {
          "title": "Two Sum",
          "problem_id": "two-sum",
          "completed": False,
          "element": <Locator>
        }
        """
        self.page.wait_for_timeout(1_000)

        selectors_to_try = [
            # Problem rows in the right content panel
            "[class*='lesson-list'] li",
            "[class*='LessonList'] li",
            "[class*='problem-list'] li",
            "ul[class*='lesson'] li",
            "ul[class*='problem'] li",
            # Generic list items that appear to the right of chapters
            "div[class*='content'] li",
            "div[class*='curriculum'] li",
            # Broad fallback: any li that contains a circle/radio icon (problem indicator)
            "li:has([class*='circle']), li:has(svg)",
        ]

        rows = []
        for sel in selectors_to_try:
            rows = self.page.locator(sel).all()
            if len(rows) > 0:
                logger.debug(f"Problem selector matched: {sel} ({len(rows)} rows)")
                break

        problems = []
        for row in rows:
            try:
                text = row.inner_text().strip()
                if not text or len(text) < 2:
                    continue

                # Skip headers like "Day 1", "Chapters"
                if text.lower().startswith("day ") and len(text) < 10:
                    continue

                # Check completion (green check icon)
                completed = False
                try:
                    row.locator("[class*='check'], [class*='complete'], [fill='green'], svg[color='green']").wait_for(timeout=300)
                    completed = True
                except PWTimeout:
                    pass

                # problem_id from title slug
                problem_id = text.lower().strip().replace(" ", "-").replace("'", "")

                problems.append({
                    "title": text,
                    "problem_id": problem_id,
                    "completed": completed,
                    "element": row,
                })
            except Exception as e:
                logger.debug(f"Skipped problem row: {e}")
                continue

        logger.info(f"Found {len(problems)} problem(s) in chapter")
        return problems

    def click_problem(self, problem: Dict) -> bool:
        """Click a problem row to open its detail page."""
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
        """
        Click the 'Take Challenge' button on the problem detail page.
        Returns True if clicked successfully.
        """
        sel = BYTESONE_CHALLENGE["take_challenge"]
        try:
            btn = self.page.locator(sel).first
            btn.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
            btn.click()
            logger.info("Clicked 'Take Challenge'")
            self.page.wait_for_timeout(1_500)  # wait for dialog
            return True
        except PWTimeout:
            logger.error("'Take Challenge' button not found")
            return False

    def handle_contest_dialog(self) -> bool:
        """
        Handle the two-step LeetCode Contest confirmation dialog:
          Step 1: username shown + "Continue" button
          Step 2: checkbox + "Start Contest" button
        Returns True if dialog handled successfully.
        """
        # Step 1 — "Continue" button (confirms username is correct)
        try:
            btn = self.page.locator(BYTESONE_CHALLENGE["dialog_continue_btn"]).first
            btn.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
            btn.click()
            logger.debug("Dialog step 1: clicked Continue")
            self.page.wait_for_timeout(1_000)
        except PWTimeout:
            logger.debug("No 'Continue' dialog step found — skipping to step 2")

        # Step 2 — checkbox + "Start Contest"
        try:
            checkbox = self.page.locator(BYTESONE_CHALLENGE["dialog_checkbox"]).first
            checkbox.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
            if not checkbox.is_checked():
                checkbox.check()
                logger.debug("Dialog step 2: checkbox checked")
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
        """Click 'Next Lesson' to advance to the next problem."""
        sel = BYTESONE_CHALLENGE["next_lesson_btn"]
        try:
            btn = self.page.locator(sel).first
            btn.wait_for(state="visible", timeout=TIMEOUT_SHORT)
            btn.click()
            self.page.wait_for_load_state("networkidle")
            logger.debug("Clicked 'Next Lesson'")
            return True
        except PWTimeout:
            logger.debug("'Next Lesson' not found — may be last problem in chapter")
            return False

    # ── helpers ────────────────────────────────────────────────────────────────

    def get_current_url(self) -> str:
        return self.page.url

    def wait_for_navigation(self):
        self.page.wait_for_load_state("networkidle")
