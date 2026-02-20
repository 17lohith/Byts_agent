"""LeetCode problem fetching, solving, and submission with robust selector fallbacks."""

import re
import time
from typing import Optional
from playwright.sync_api import Page, TimeoutError as PWTimeout

from src.config.constants import LEETCODE_SELECTORS, TIMEOUT_SHORT, TIMEOUT_MEDIUM, TIMEOUT_LONG
from src.ai.solver import LLMSolver
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class LeetCodeSolver:
    def __init__(self, page: Page, llm: LLMSolver):
        from src.config.settings import settings
        self.page = page
        self.llm = llm
        self.settings = settings

    # ------------------------------------------------------------------ public

    def solve_problem(self, url: str) -> bool:
        """
        Navigate to a LeetCode problem, generate a solution with the LLM, submit it.
        Returns True if the submission is accepted within the retry budget.
        """
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                logger.info(f"Attempt {attempt}/{self.settings.max_retries}: {url}")
                self.page.goto(url)
                self.page.wait_for_load_state("networkidle")

                # Check if LeetCode is asking us to log in
                if self._is_login_wall():
                    logger.warning("LeetCode login wall detected — triggering re-auth")
                    return False  # caller (main) handles re-auth

                title = self._get_title()
                description = self._get_description()
                if not title or not description:
                    logger.error("Could not extract problem title/description — skipping")
                    return False

                code = self.llm.solve(title, description)
                code = self._strip_markdown(code)
                logger.debug(f"Generated code ({len(code)} chars)")

                if not self._enter_code(code):
                    logger.warning("Code injection failed — retrying")
                    time.sleep(self.settings.retry_delay)
                    continue

                if self._submit_and_wait():
                    logger.info(f"Accepted: {title} ✅")
                    return True

                logger.warning(f"Not accepted on attempt {attempt}")
                time.sleep(self.settings.retry_delay)

            except Exception as exc:
                logger.error(f"Error on attempt {attempt}: {exc}")
                time.sleep(self.settings.retry_delay)

        return False

    # ----------------------------------------------------------------- helpers

    def _is_login_wall(self) -> bool:
        for sel in LEETCODE_SELECTORS["login_wall"]:
            try:
                self.page.locator(sel).first.wait_for(state="visible", timeout=TIMEOUT_SHORT)
                return True
            except PWTimeout:
                continue
        return False

    def _get_title(self) -> Optional[str]:
        for sel in LEETCODE_SELECTORS["problem_title"]:
            try:
                el = self.page.locator(sel).first
                el.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
                text = el.inner_text().strip()
                if text:
                    logger.debug(f"Title selector matched: {sel}")
                    return text
            except PWTimeout:
                continue
        logger.error("No title selector matched")
        return None

    def _get_description(self) -> Optional[str]:
        for sel in LEETCODE_SELECTORS["problem_description"]:
            try:
                el = self.page.locator(sel).first
                el.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
                text = el.inner_text().strip()
                if text:
                    logger.debug(f"Description selector matched: {sel}")
                    return text
            except PWTimeout:
                continue
        logger.error("No description selector matched")
        return None

    def _enter_code(self, code: str) -> bool:
        """
        Inject code into Monaco editor.
        Tries JS API first, falls back to keyboard select-all + type.
        Returns True if injection appears successful.
        """
        # Wait for editor to be present
        try:
            self.page.locator(LEETCODE_SELECTORS["code_editor"]).first.wait_for(
                state="visible", timeout=TIMEOUT_LONG
            )
        except PWTimeout:
            logger.error("Monaco editor not found on page")
            return False

        # Method 1: Monaco JS API (fast and reliable)
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
            logger.warning("Monaco JS API returned false — falling back to keyboard")
        except Exception as e:
            logger.warning(f"Monaco JS API failed: {e} — falling back to keyboard")

        # Method 2: Click editor, Ctrl+A, type
        try:
            editor = self.page.locator(LEETCODE_SELECTORS["code_editor"]).first
            editor.click()
            time.sleep(0.3)
            self.page.keyboard.press("Control+a")
            time.sleep(0.1)
            self.page.keyboard.type(code, delay=10)

            # Verify: read back via Monaco
            actual = self.page.evaluate(
                "() => { const m = monaco.editor.getModels(); return m.length ? m[0].getValue() : ''; }"
            )
            if code.strip() in actual:
                logger.debug("Code injected via keyboard fallback ✅")
                return True
            logger.warning("Keyboard injection verification failed")
            return False
        except Exception as e:
            logger.error(f"Keyboard code injection failed: {e}")
            return False

    def _submit_and_wait(self) -> bool:
        # Click submit
        for sel in LEETCODE_SELECTORS["submit_button"]:
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
        try:
            for sel in LEETCODE_SELECTORS["result_accepted"]:
                try:
                    self.page.locator(sel).first.wait_for(
                        state="visible", timeout=TIMEOUT_LONG
                    )
                    return True
                except PWTimeout:
                    continue
        except Exception:
            pass
        return False

    @staticmethod
    def _strip_markdown(code: str) -> str:
        """Remove ```python … ``` fences if the LLM wrapped the code."""
        code = re.sub(r"^```[\w]*\n?", "", code, flags=re.MULTILINE)
        code = re.sub(r"\n?```$", "", code, flags=re.MULTILINE)
        return code.strip()
