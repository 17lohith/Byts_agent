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
        Navigate to Solutions page, apply Java filter, then iterate through
        solutions starting from the 2nd one until valid Java code is found.
        Returns None if no Java solution could be extracted.
        """
        if not self._open_solutions_tab():
            return None

        # Apply Java filter via URL param
        self._apply_language_filter(TARGET_LANGUAGE)
        self.page.wait_for_timeout(1_500)

        # Collect all solution detail page URLs, then iterate
        return self._find_java_solution()

    # ── private steps ──────────────────────────────────────────────────────────

    def _find_java_solution(self) -> Optional[str]:
        """
        Collect all solution URLs from the listing page and try each one
        (starting from the 2nd) until valid Java code is found.
        """
        links = self._get_solution_links()

        if not links:
            logger.warning("No solution links found on solutions page")
            return self._fallback_first_code_block()

        logger.info(f"Found {len(links)} solution links — trying from 2nd onwards")

        # Start from index 1 (2nd solution) to skip potentially locked/premium 1st,
        # then fall back to the 1st if nothing else works.
        order = list(range(1, len(links))) + [0] if len(links) > 1 else [0]

        for attempt_num, idx in enumerate(order[:10], 1):  # try up to 10
            url = links[idx]
            logger.info(f"Solution attempt {attempt_num} (list position {idx + 1}): {url}")
            try:
                self.page.goto(url)
                self.page.wait_for_load_state("load")
                self.page.wait_for_timeout(2_000)
            except Exception as e:
                logger.debug(f"Navigation failed for {url}: {e}")
                continue

            code = self._extract_code_from_solution_page()
            if code and _is_valid_java(code):
                logger.info(f"Valid Java solution found at position {idx + 1} ({len(code)} chars) ✅")
                return code

            logger.debug(f"Position {idx + 1} has no valid Java code — trying next")

        logger.warning("No valid Java solution found after trying all available solutions")
        return None

    def _get_solution_links(self) -> List[str]:
        """Collect all solution detail page URLs from the current solutions listing."""
        links: List[str] = []
        seen: set = set()
        try:
            for a in self.page.locator("a[href*='/solutions/']").all():
                try:
                    href = a.get_attribute("href", timeout=500)
                    if not href:
                        continue
                    full = href if href.startswith("http") else f"https://leetcode.com{href}"
                    # Skip the solutions listing page itself
                    if full.rstrip("/").endswith("/solutions"):
                        continue
                    if full not in seen:
                        seen.add(full)
                        links.append(full)
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Error collecting solution links: {e}")
        return links

    def _open_solutions_tab(self) -> bool:
        """
        Navigate directly to the /solutions/ URL for the current problem.
        This is more reliable than looking for a Solutions tab in the UI,
        which LeetCode changes frequently.
        """
        current_url = self.page.url

        # Fail fast with a clear message if the page reference is wrong
        if 'leetcode.com' not in current_url:
            logger.error(f"_open_solutions_tab called on non-LeetCode page: {current_url}")
            return False

        # Extract base problem URL: https://leetcode.com/problems/{slug}
        m = re.match(r'(https://leetcode\.com/problems/[^/?#]+)', current_url)
        if m:
            base = m.group(1).rstrip('/')
            solutions_url = f"{base}/solutions/"
            logger.info(f"Navigating directly to solutions page: {solutions_url}")
            for attempt in range(3):
                try:
                    self.page.goto(solutions_url)
                    self.page.wait_for_load_state("load")
                    self.page.wait_for_timeout(1_500)
                    logger.info("Opened LeetCode Solutions page ✅")
                    return True
                except Exception as e:
                    if attempt < 2:
                        logger.warning(f"Solutions page navigation failed (attempt {attempt+1}/3): {e} — retrying…")
                        time.sleep(2)
                    else:
                        logger.error(f"Solutions page navigation failed after 3 attempts: {e}")
            return False

        # Fallback: try clicking a Solutions tab in the UI
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
                self.page.wait_for_load_state("load")
                self.page.wait_for_timeout(1_500)
                logger.info("Opened LeetCode Solutions tab ✅")
                return True
            except PWTimeout:
                continue
        logger.error("Could not navigate to Solutions page")
        return False

    def _apply_language_filter(self, language: str):
        """
        Apply language filter via URL parameter — much more reliable than UI clicks.
        LeetCode supports: ?languageTags=java
        """
        current_url = self.page.url
        lang_param = language.lower()  # "java"

        # Build new URL with languageTags param
        if '?' in current_url:
            if 'languageTags' in current_url:
                return  # already filtered
            new_url = f"{current_url}&languageTags={lang_param}"
        else:
            new_url = f"{current_url}?languageTags={lang_param}"

        logger.debug(f"Applying language filter via URL: {new_url}")
        self.page.goto(new_url)
        self.page.wait_for_load_state("load")
        self.page.wait_for_timeout(1_000)
        logger.debug(f"Language filter set to {language} ✅")

    def _extract_code_from_solution_page(self) -> Optional[str]:
        """
        On a solution detail page, find and extract the Java code.
        Tries multiple strategies in order of reliability.
        """
        # Strategy 1: Read-only Monaco editor (LeetCode embeds this in solution pages)
        try:
            code = self.page.evaluate(
                """() => {
                    if (typeof monaco !== 'undefined') {
                        const models = monaco.editor.getModels();
                        if (models && models.length > 0) return models[0].getValue();
                    }
                    return null;
                }"""
            )
            if code and len(code) > 20:
                logger.info(f"Extracted code via Monaco JS ({len(code)} chars) ✅")
                return code
        except Exception:
            pass

        # Strategy 2: DOM selectors
        code_selectors = [
            "pre code",
            ".view-lines",
            "[class*='CodeMirror'] .CodeMirror-code",
            "[class*='hljs']",
            "code[class*='language-java']",
            "code[class*='language-']",
            "code",
            "pre",
        ]
        for sel in code_selectors:
            try:
                el = self.page.locator(sel).first
                el.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
                code = el.inner_text().strip()
                if code and len(code) > 20:
                    logger.info(f"Extracted solution code via DOM ({len(code)} chars) ✅")
                    return code
            except PWTimeout:
                continue

        # Strategy 3: Copy button / clipboard
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
        """Parse a vote/like count number from card text (kept for compatibility)."""
        patterns = [r"(\d+\.?\d*)[Kk]", r"(\d+)"]
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


# ── module-level helpers ────────────────────────────────────────────────────────

def _is_valid_java(code: str) -> bool:
    """
    Return True if extracted code looks like a real Java solution.
    Rejects empty stubs, truncated previews, and non-Java code.
    """
    if not code or len(code) < 150:  # stubs are usually < 100 chars
        return False
    java_keywords = ["class ", "public ", "return ", "{", "}"]
    return sum(1 for kw in java_keywords if kw in code) >= 4
