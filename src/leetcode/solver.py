"""LeetCode problem fetching and solution submission."""

import re
import time
from playwright.sync_api import Page

from src.config.constants import LEETCODE_SELECTORS
from src.ai.solver import LLMSolver
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class LeetCodeSolver:
    def __init__(self, page: Page, llm: LLMSolver):
        from src.config.settings import settings
        self.page = page
        self.llm = llm
        self.settings = settings

    def solve_problem(self, url: str) -> bool:
        """Navigate to a LeetCode problem, solve it with the LLM, and submit.

        Returns True if the submission is accepted within the retry budget.
        """
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                logger.info(f"Attempt {attempt}/{self.settings.max_retries}: {url}")
                self.page.goto(url)
                self.page.wait_for_load_state("networkidle")

                title = self._get_title()
                description = self._get_description()

                code = self.llm.solve(title, description)
                code = self._strip_markdown(code)

                self._enter_code(code)
                if self._submit_and_wait():
                    logger.info(f"✅ Accepted: {title}")
                    return True

                logger.warning(f"❌ Not accepted on attempt {attempt}")
                time.sleep(self.settings.retry_delay)

            except Exception as exc:
                logger.error(f"Error on attempt {attempt}: {exc}")
                time.sleep(self.settings.retry_delay)

        return False

    # ------------------------------------------------------------------ helpers

    def _get_title(self) -> str:
        el = self.page.locator(LEETCODE_SELECTORS["problem_title"]).first
        el.wait_for()
        return el.inner_text().strip()

    def _get_description(self) -> str:
        el = self.page.locator(LEETCODE_SELECTORS["problem_description"]).first
        el.wait_for()
        return el.inner_text().strip()

    def _enter_code(self, code: str):
        # Use Monaco editor JS API to set value directly — fast and reliable
        self.page.evaluate(
            "(code) => { const model = monaco.editor.getModels()[0]; model.setValue(code); }",
            code,
        )

    def _submit_and_wait(self) -> bool:
        self.page.locator(LEETCODE_SELECTORS["submit_button"]).click()
        try:
            self.page.locator(LEETCODE_SELECTORS["result_accepted"]).wait_for(
                timeout=30_000
            )
            return True
        except Exception:
            return False

    @staticmethod
    def _strip_markdown(code: str) -> str:
        """Remove ```python ... ``` fences if the LLM added them."""
        code = re.sub(r"^```[\w]*\n?", "", code, flags=re.MULTILINE)
        code = re.sub(r"\n?```$", "", code, flags=re.MULTILINE)
        return code.strip()
