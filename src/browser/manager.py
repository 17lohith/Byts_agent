"""Playwright browser manager — persistent Chromium context (no CDP needed)."""

import os
from playwright.sync_api import sync_playwright, BrowserContext, Page

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class BrowserManager:
    """
    Launches a persistent Chromium browser using Playwright's own bundled browser.

    Profile directory is kept between runs so cookies / localStorage survive.
    On first run the browser opens headed so the user can complete Google OAuth
    manually.  After that the saved storage_state.json is reloaded automatically.
    """

    def __init__(self):
        from src.config.settings import settings
        self.settings = settings
        self._playwright = None
        self._context: BrowserContext = None
        self.page: Page = None

    # ------------------------------------------------------------------ public

    def start(self):
        logger.info("Launching Playwright Chromium (persistent context) …")
        self._playwright = sync_playwright().start()

        profile_dir = os.path.abspath(self.settings.browser_profile_dir)
        os.makedirs(profile_dir, exist_ok=True)

        # launch_persistent_context keeps cookies + localStorage across runs
        launch_kwargs = dict(
            user_data_dir=profile_dir,
            headless=self.settings.headless,
            slow_mo=self.settings.slow_mo,
            args=[
                "--disable-blink-features=AutomationControlled",  # avoid bot detection
                "--no-first-run",
                "--no-default-browser-check",
            ],
            ignore_default_args=["--enable-automation"],
        )

        # persistent context stores session in user_data_dir automatically —
        # storage_state is NOT a valid kwarg for launch_persistent_context
        session_exists = os.path.exists(self.settings.session_file)
        if session_exists:
            logger.info("Persistent profile found — existing session will be reused")
        else:
            logger.info("No saved session — first-run mode (manual login required)")

        self._context = self._playwright.chromium.launch_persistent_context(
            **launch_kwargs
        )
        self._context.set_default_timeout(self.settings.page_timeout)
        self._context.set_default_navigation_timeout(self.settings.navigation_timeout)

        # Reuse existing tab or open a blank one
        self.page = (
            self._context.pages[0]
            if self._context.pages
            else self._context.new_page()
        )
        logger.info("Browser ready ✅")

    def save_session(self):
        """Persist cookies + storage so the next run skips manual login."""
        self._context.storage_state(path=self.settings.session_file)
        logger.info(f"Session saved → {self.settings.session_file}")

    def stop(self):
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
        if self._playwright:
            self._playwright.stop()
        logger.info("Browser closed")

    # ----------------------------------------------------------------- context

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
