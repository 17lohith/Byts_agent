"""BytsOne platform navigation with login detection and fuzzy course matching."""

import time
from typing import List, Dict, Optional
from playwright.sync_api import Page, TimeoutError as PWTimeout

from src.config.constants import BYTESONE_SELECTORS, TIMEOUT_SHORT, TIMEOUT_MEDIUM
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class BytesOneNavigator:
    def __init__(self, page: Page):
        from src.config.settings import settings
        self.page = page
        self.settings = settings

    # ------------------------------------------------------------------ public

    def navigate_to_course(self) -> bool:
        """
        Open BytsOne dashboard and navigate into the configured course.
        Returns True on success.
        """
        logger.info(f"Opening BytsOne: {self.settings.bytesone_url}")
        self.page.goto(self.settings.bytesone_url)
        self.page.wait_for_load_state("networkidle")

        # Click "Courses" in the sidebar
        self._click_safe(BYTESONE_SELECTORS["sidebar_courses"], "sidebar Courses")
        self.page.wait_for_load_state("networkidle")

        # Find and click the course — try exact match first, then partial
        course = self._find_course()
        if course is None:
            logger.error(
                f"Course not found: '{self.settings.course_name}'. "
                "Check COURSE_NAME in your .env file."
            )
            return False

        course.click()
        self.page.wait_for_load_state("networkidle")
        logger.info(f"Opened course: {self.settings.course_name} ✅")
        return True

    def get_problem_links(self) -> List[Dict[str, str]]:
        """Return all LeetCode problem links on the current course page."""
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2_000)  # let dynamic content render

        anchors = self.page.locator("a[href*='leetcode.com/problems']").all()
        problems = []
        for a in anchors:
            href = a.get_attribute("href") or ""
            title = a.inner_text().strip() or href
            if href:
                problems.append({"url": href, "title": title})

        logger.info(f"Found {len(problems)} LeetCode problem(s)")
        return problems

    def mark_completed(self):
        """Click 'Mark as Completed' on the current BytsOne problem if visible."""
        try:
            btn = self.page.locator(BYTESONE_SELECTORS["mark_completed"]).first
            btn.wait_for(state="visible", timeout=TIMEOUT_SHORT)
            btn.click()
            time.sleep(1)
            logger.info("Marked as completed on BytsOne ✅")
        except PWTimeout:
            logger.warning("'Mark as Completed' button not found — skipping")
        except Exception as e:
            logger.warning(f"Could not mark completed: {e}")

    # ----------------------------------------------------------------- helpers

    def _find_course(self):
        """
        Try to locate the course link element.
        Strategy: exact text → partial text → first result containing any word.
        """
        name = self.settings.course_name

        # 1. Exact match
        loc = self.page.locator(f"text={name}").first
        if self._is_visible(loc):
            return loc

        # 2. Partial match — first element whose text contains the full course name
        loc = self.page.locator(f":text-is('{name}')").first
        if self._is_visible(loc):
            return loc

        # 3. Fuzzy — match on the longest unique substring (first 40 chars)
        snippet = name[:40]
        loc = self.page.locator(f"text={snippet}").first
        if self._is_visible(loc):
            logger.warning(f"Used fuzzy match for course name: '{snippet}…'")
            return loc

        return None

    def _click_safe(self, selector: str, label: str = ""):
        try:
            el = self.page.locator(selector).first
            el.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
            el.click()
        except PWTimeout:
            logger.warning(f"Element not visible — skipped: {label or selector}")
        except Exception as e:
            logger.warning(f"Click failed ({label or selector}): {e}")

    @staticmethod
    def _is_visible(locator) -> bool:
        try:
            locator.wait_for(state="visible", timeout=TIMEOUT_SHORT)
            return True
        except Exception:
            return False
