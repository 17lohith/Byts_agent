"""BytsOne platform navigation."""

import time
from typing import List, Dict
from playwright.sync_api import Page

from src.config.constants import BYTESONE_SELECTORS
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class BytesOneNavigator:
    def __init__(self, page: Page):
        from src.config.settings import settings
        self.page = page
        self.settings = settings

    def navigate_to_course(self) -> bool:
        """Go to BytsOne and open the configured course. Returns True on success."""
        logger.info(f"Opening BytsOne: {self.settings.bytesone_url}")
        self.page.goto(self.settings.bytesone_url)
        self.page.wait_for_load_state("networkidle")

        # Click Courses in the sidebar
        try:
            self.page.locator(BYTESONE_SELECTORS["sidebar_courses"]).click()
            self.page.wait_for_load_state("networkidle")
        except Exception as e:
            logger.warning(f"Sidebar courses click skipped: {e}")

        # Find the course by name
        try:
            self.page.locator(f"text={self.settings.course_name}").first.click()
            self.page.wait_for_load_state("networkidle")
            logger.info(f"Opened course: {self.settings.course_name}")
            return True
        except Exception as e:
            logger.error(f"Course not found '{self.settings.course_name}': {e}")
            return False

    def get_problem_links(self) -> List[Dict[str, str]]:
        """Return all LeetCode problem links on the current page."""
        # Wait for dynamic content to finish loading
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)
        anchors = self.page.locator("a[href*='leetcode.com/problems']").all()
        problems = []
        for a in anchors:
            href = a.get_attribute("href") or ""
            title = a.inner_text().strip() or href
            if href:
                problems.append({"url": href, "title": title})
        logger.info(f"Found {len(problems)} LeetCode problem(s)")
        return problems

    def activate_challenge(self):
        """Click Activate or Take Challenge if present."""
        for key in ("activate_button", "take_challenge"):
            try:
                btn = self.page.locator(BYTESONE_SELECTORS[key]).first
                if btn.is_visible():
                    btn.click()
                    self.page.wait_for_load_state("networkidle")
                    logger.info(f"Clicked: {key}")
                    return
            except Exception:
                pass

    def mark_completed(self):
        """Click the Mark as Completed button if visible."""
        try:
            btn = self.page.locator(BYTESONE_SELECTORS["mark_completed"]).first
            if btn.is_visible():
                btn.click()
                time.sleep(1)
                logger.info("Marked as completed on BytsOne ✅")
        except Exception as e:
            logger.warning(f"Could not mark completed: {e}")
