"""Playwright browser — launches Chromium with a persistent profile."""

import os
from playwright.sync_api import sync_playwright, BrowserContext, Page

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class BrowserManager:
    def __init__(self):
        from src.config.settings import settings
        self.settings = settings
        self._playwright = None
        self._context: BrowserContext = None
        self.page: Page = None

    def start(self):
        logger.info("Launching Playwright Chromium (persistent context) …")
        self._playwright = sync_playwright().start()

        profile_dir = os.path.abspath(self.settings.browser_profile_dir)
        if os.path.exists(profile_dir):
            logger.info("Persistent profile found — existing session will be reused")
        else:
            logger.info("No profile found — fresh browser (you will need to log in)")

        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=self.settings.headless,
            slow_mo=self.settings.slow_mo,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context.set_default_timeout(self.settings.page_timeout)
        self._context.set_default_navigation_timeout(self.settings.navigation_timeout)

        self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
        logger.info("Browser ready ✅")

    def save_session(self):
        try:
            self._context.storage_state(path=self.settings.session_file)
            logger.info(f"Session saved → {self.settings.session_file}")
        except Exception as e:
            logger.warning(f"Could not save session: {e}")

    def stop(self):
        try:
            self._context.close()
        except Exception:
            pass
        try:
            self._playwright.stop()
        except Exception:
            pass
        logger.info("Browser closed")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
