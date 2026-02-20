"""LeetCode problem solver — uses Solutions tab for code, then submits."""

import re
import time
from typing import Optional
from playwright.sync_api import Page, TimeoutError as PWTimeout

from src.config.constants import (
    LEETCODE_PROBLEM, LEETCODE_EDITOR,
    TIMEOUT_SHORT, TIMEOUT_MEDIUM, TIMEOUT_LONG,
)
from src.leetcode.solutions import LeetCodeSolutionScraper
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class LeetCodeSolver:
    def __init__(self, page: Page):
        from src.config.settings import settings
        self.page = page
        self.settings = settings
        self.scraper = LeetCodeSolutionScraper(page)

    # ── public ─────────────────────────────────────────────────────────────────

    def solve_current_problem(self) -> bool:
        """
        The bot is already on the LeetCode problem page (redirected from BytsOne).
        1. Check if already Accepted — skip if so.
        2. Get best Java solution from Solutions tab.
        3. Switch editor to Java, inject code, submit.
        4. Return True on Accepted.
        """
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1_500)

        current_url = self.page.url
        logger.info(f"On LeetCode: {current_url}")

        # Check if already solved
        if self._is_already_accepted():
            logger.info("Problem already Accepted — skipping re-submit ✅")
            return True

        # Get solution from Solutions tab
        code = self.scraper.get_best_solution()
        if not code:
            logger.error("Could not get any solution code — skipping problem")
            return False

        code = _strip_markdown(code)
        logger.debug(f"Solution code ({len(code)} chars)")

        # Navigate back to Description tab to get the code editor
        self._go_to_description_tab()
        self.page.wait_for_timeout(1_000)

        # Switch language to Java in the editor
        self._switch_language_to_java()

        # Inject code
        if not self._enter_code(code):
            logger.error("Code injection failed")
            return False

        # Submit and wait for result
        for attempt in range(1, self.settings.max_retries + 1):
            logger.info(f"Submitting … (attempt {attempt}/{self.settings.max_retries})")
            if self._submit_and_wait():
                logger.info("Accepted ✅")
                return True
            logger.warning(f"Not accepted on attempt {attempt}")
            time.sleep(self.settings.retry_delay)

        return False

    # ── navigation helpers ─────────────────────────────────────────────────────

    def _go_to_description_tab(self):
        """Navigate back to Description tab (where the code editor lives)."""
        selectors = [
            "a:has-text('Description')",
            "div[role='tab']:has-text('Description')",
            "li:has-text('Description')",
        ]
        for sel in selectors:
            try:
                tab = self.page.locator(sel).first
                tab.wait_for(state="visible", timeout=TIMEOUT_SHORT)
                tab.click()
                self.page.wait_for_timeout(1_000)
                return
            except PWTimeout:
                continue
        logger.debug("Description tab not found — may already be active")

    def _switch_language_to_java(self):
        """Switch the code editor language dropdown to Java."""
        lang_btn_selectors = [
            "button[id*='headlessui']:has-text('Java')",    # already Java
            "button[id*='headlessui']",                     # generic lang button
            "[class*='lang'] button",
            "button[class*='lang']",
        ]
        for sel in lang_btn_selectors:
            try:
                btn = self.page.locator(sel).first
                btn.wait_for(state="visible", timeout=TIMEOUT_SHORT)
                btn_text = btn.inner_text().strip().lower()
                if "java" in btn_text and "javascript" not in btn_text:
                    logger.debug("Editor already set to Java")
                    return
                btn.click()
                self.page.wait_for_timeout(500)
                # Pick Java from dropdown
                java_option = self.page.locator(
                    "text=Java, li:has-text('Java')"
                ).first
                java_option.wait_for(state="visible", timeout=TIMEOUT_SHORT)
                java_option.click()
                self.page.wait_for_timeout(500)
                logger.debug("Switched editor to Java")
                return
            except PWTimeout:
                continue
        logger.warning("Could not switch language to Java — proceeding anyway")

    # ── code injection ─────────────────────────────────────────────────────────

    def _enter_code(self, code: str) -> bool:
        """Inject code into Monaco editor. JS API first, keyboard fallback."""
        # Wait for editor
        try:
            self.page.locator(LEETCODE_EDITOR["code_editor"]).first.wait_for(
                state="visible", timeout=TIMEOUT_LONG
            )
        except PWTimeout:
            logger.error("Monaco editor not found")
            return False

        # Method 1: Monaco JS API
        try:
            result = self.page.evaluate(
                """(code) => {
                    const models = monaco.editor.getModels();
                    if (!models || models.length === 0) return false;
                    models[0].setValue(code);
                    return models[0].getValue() === code;
                }""",
                code,
            )
            if result:
                logger.debug("Code injected via Monaco JS API ✅")
                return True
        except Exception as e:
            logger.warning(f"Monaco JS API failed: {e}")

        # Method 2: Keyboard
        try:
            editor = self.page.locator(LEETCODE_EDITOR["code_editor"]).first
            editor.click()
            time.sleep(0.3)
            self.page.keyboard.press("Control+a")
            time.sleep(0.1)
            self.page.keyboard.type(code, delay=5)
            # Verify
            actual = self.page.evaluate(
                "() => { const m = monaco.editor.getModels(); return m.length ? m[0].getValue() : ''; }"
            )
            if code.strip()[:50] in actual:
                logger.debug("Code injected via keyboard ✅")
                return True
        except Exception as e:
            logger.error(f"Keyboard injection failed: {e}")

        return False

    # ── submission ─────────────────────────────────────────────────────────────

    def _submit_and_wait(self) -> bool:
        for sel in LEETCODE_EDITOR["submit_button"]:
            try:
                btn = self.page.locator(sel).first
                btn.wait_for(state="visible", timeout=TIMEOUT_SHORT)
                btn.click()
                break
            except PWTimeout:
                continue
        else:
            logger.error("Submit button not found")
            return False

        # Wait for result
        for sel in LEETCODE_EDITOR["result_accepted"]:
            try:
                self.page.locator(sel).first.wait_for(
                    state="visible", timeout=TIMEOUT_LONG
                )
                return True
            except PWTimeout:
                continue
        return False

    # ── status checks ──────────────────────────────────────────────────────────

    def _is_already_accepted(self) -> bool:
        """Check if this problem already shows Accepted status."""
        for sel in LEETCODE_PROBLEM["accepted_badge"]:
            try:
                self.page.locator(sel).first.wait_for(state="visible", timeout=2_000)
                return True
            except PWTimeout:
                continue
        return False

    def _is_login_wall(self) -> bool:
        for sel in LEETCODE_PROBLEM["login_wall"]:
            try:
                self.page.locator(sel).first.wait_for(state="visible", timeout=2_000)
                return True
            except PWTimeout:
                continue
        return False


# ── helpers ────────────────────────────────────────────────────────────────────

def _strip_markdown(code: str) -> str:
    code = re.sub(r"^```[\w]*\n?", "", code, flags=re.MULTILINE)
    code = re.sub(r"\n?```$", "", code, flags=re.MULTILINE)
    return code.strip()
