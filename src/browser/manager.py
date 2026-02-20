"""Playwright browser — attaches to your existing Brave session via CDP."""

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
        logger.info(f"Attaching to Brave at {self.settings.cdp_url} …")
        self._playwright = sync_playwright().start()

        try:
            browser = self._playwright.chromium.connect_over_cdp(self.settings.cdp_url)
        except Exception:
            raise RuntimeError(
                f"\n❌ Could not connect to Brave at {self.settings.cdp_url}\n"
                "Make sure Brave is running with remote debugging:\n\n"
                '  open -a "Brave Browser" --args --remote-debugging-port=9222\n'
            )

        self._context = browser.contexts[0]
        # Reuse the active tab if one exists, otherwise open a new one
        self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self._context.set_default_timeout(self.settings.page_timeout)
        self._context.set_default_navigation_timeout(self.settings.navigation_timeout)
        logger.info("Connected to Brave ✅  (your existing session will be used)")

    def stop(self):
        # Never close the user's Brave — just detach
        if self._playwright:
            self._playwright.stop()
        logger.info("Detached from Brave")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
