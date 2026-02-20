"""LeetCode Solutions tab scraper — finds and copies the most upvoted Java solution."""

import time
import re
from typing import Optional, List
from playwright.sync_api import Page, TimeoutError as PWTimeout

from src.config.constants import (
    LEETCODE_SOLUTIONS, LEETCODE_EDITOR,
    TIMEOUT_SHORT, TIMEOUT_MEDIUM, TIMEOUT_LONG,
)
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

TARGET_LANGUAGE = "Java"


class LeetCodeSolutionScraper:
    def __init__(self, page: Page):
        self.page = page

    # ── public API ─────────────────────────────────────────────────────────────

    def get_best_solution(self) -> Optional[str]:
        """
        On the current LeetCode problem page, navigate to the Solutions tab,
        find the most upvoted Java solution, open it, and return the code.
        Returns None if no Java solution is found.
        """
        if not self._open_solutions_tab():
            return None

        # Filter by Java language
        self._apply_language_filter(TARGET_LANGUAGE)
        self.page.wait_for_timeout(1_500)

        # Get all solution cards and pick most upvoted
        code = self._pick_most_upvoted_solution()
        return code

    # ── private steps ──────────────────────────────────────────────────────────

    def _open_solutions_tab(self) -> bool:
        """Click the Solutions tab on the LeetCode problem page."""
        selectors = [
            "a:has-text('Solutions')",
            "div[role='tab']:has-text('Solutions')",
            "button:has-text('Solutions')",
            "li:has-text('Solutions')",
        ]
        for sel in selectors:
            try:
                tab = self.page.locator(sel).first
                tab.wait_for(state="visible", timeout=TIMEOUT_SHORT)
                tab.click()
                self.page.wait_for_load_state("networkidle")
                self.page.wait_for_timeout(1_500)
                logger.info("Opened LeetCode Solutions tab ✅")
                return True
            except PWTimeout:
                continue
        logger.error("Could not find Solutions tab")
        return False

    def _apply_language_filter(self, language: str):
        """Try to filter solutions by language. Silently skip if filter not found."""
        lang_filter_selectors = [
            f"button:has-text('{language}')",
            f"[class*='filter']:has-text('{language}')",
            "select[class*='lang']",
            "[class*='LanguageFilter']",
            "div[class*='filter'] button",
        ]
        for sel in lang_filter_selectors:
            try:
                el = self.page.locator(sel).first
                el.wait_for(state="visible", timeout=TIMEOUT_SHORT)
                if el.evaluate("e => e.tagName") == "SELECT":
                    el.select_option(label=language)
                else:
                    el.click()
                    # If dropdown opened, pick Java option
                    try:
                        opt = self.page.locator(f"li:has-text('{language}'), option:has-text('{language}')").first
                        opt.wait_for(state="visible", timeout=TIMEOUT_SHORT)
                        opt.click()
                    except PWTimeout:
                        pass
                self.page.wait_for_timeout(1_000)
                logger.debug(f"Language filter set to {language}")
                return
            except PWTimeout:
                continue
        logger.warning(f"Could not apply {language} filter — proceeding without filter")

    def _pick_most_upvoted_solution(self) -> Optional[str]:
        """
        Parse solution cards, find the one with highest upvotes that is a Java solution,
        click it, and extract the code.
        """
        # Collect solution cards
        card_selectors = [
            "[class*='solution-card']",
            "[class*='SolutionCard']",
            "[class*='solution__']",
            "div[class*='topic-item']",
            "div[class*='titleSlug']",
            # Very broad — any div that has a vote count and a title
            "div:has([class*='vote']):has(a[href*='/solutions/'])",
        ]

        cards = []
        for sel in card_selectors:
            cards = self.page.locator(sel).all()
            if cards:
                logger.debug(f"Solution card selector: {sel} ({len(cards)} cards)")
                break

        if not cards:
            logger.warning("No solution cards found on Solutions tab")
            return self._fallback_first_code_block()

        # Score cards by upvote count + Java preference
        best_card = None
        best_score = -1

        for card in cards:
            try:
                card_text = card.inner_text().strip()

                # Prefer Java solutions
                is_java = "java" in card_text.lower()

                # Extract vote count
                votes = self._extract_vote_count(card_text)

                # Score: Java gets a big bonus
                score = votes + (100_000 if is_java else 0)

                if score > best_score:
                    best_score = score
                    best_card = card

            except Exception:
                continue

        if best_card is None:
            logger.warning("Could not score any solution cards")
            return self._fallback_first_code_block()

        # Click the best card to open it
        return self._open_solution_card(best_card)

    def _open_solution_card(self, card) -> Optional[str]:
        """Click a solution card and extract the code from the solution detail page."""
        try:
            # Try clicking the title link inside the card
            link = card.locator("a[href*='/solutions/']").first
            link.wait_for(state="visible", timeout=TIMEOUT_SHORT)
            link.click()
        except PWTimeout:
            try:
                card.click()
            except Exception as e:
                logger.error(f"Could not click solution card: {e}")
                return None

        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2_000)

        return self._extract_code_from_solution_page()

    def _extract_code_from_solution_page(self) -> Optional[str]:
        """
        On a solution detail page, find and extract the Java code.
        Tries multiple selector strategies.
        """
        code_selectors = [
            "pre code",
            ".view-lines",
            "[class*='CodeMirror'] .CodeMirror-code",
            "[class*='hljs']",
            "code[class*='language-java']",
            "code",
            "pre",
        ]

        for sel in code_selectors:
            try:
                el = self.page.locator(sel).first
                el.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
                code = el.inner_text().strip()
                if code and len(code) > 20:  # sanity check
                    logger.info(f"Extracted solution code ({len(code)} chars) ✅")
                    return code
            except PWTimeout:
                continue

        # Last resort: copy via clipboard
        logger.warning("Could not extract code via DOM — trying clipboard copy")
        return self._extract_via_copy_button()

    def _extract_via_copy_button(self) -> Optional[str]:
        """Try clicking a 'Copy' button if present and read clipboard."""
        try:
            copy_btn = self.page.locator(
                "button:has-text('Copy'), [aria-label*='copy'], [title*='copy']"
            ).first
            copy_btn.wait_for(state="visible", timeout=TIMEOUT_SHORT)
            copy_btn.click()
            time.sleep(0.5)
            # Read clipboard via JS
            code = self.page.evaluate("() => navigator.clipboard.readText()")
            if code:
                logger.info(f"Extracted code via clipboard ({len(code)} chars)")
                return code
        except Exception as e:
            logger.debug(f"Clipboard extraction failed: {e}")
        return None

    def _fallback_first_code_block(self) -> Optional[str]:
        """Emergency fallback: grab the first code block on the solutions page."""
        try:
            el = self.page.locator("pre code, pre, code").first
            el.wait_for(state="visible", timeout=TIMEOUT_SHORT)
            code = el.inner_text().strip()
            if code:
                logger.warning("Using fallback: first code block on page")
                return code
        except PWTimeout:
            pass
        return None

    @staticmethod
    def _extract_vote_count(text: str) -> int:
        """Parse a vote/like count number from card text."""
        # Look for patterns like "1.2K", "345", "K"
        patterns = [
            r"(\d+\.?\d*)[Kk]",   # e.g. 1.2K
            r"(\d+)",             # plain integer
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                val = m.group(1)
                try:
                    num = float(val)
                    if "k" in text[m.start():m.end()+1].lower():
                        num *= 1000
                    return int(num)
                except ValueError:
                    pass
        return 0
