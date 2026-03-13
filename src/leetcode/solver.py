"""LeetCode problem solver — web scraping first, then AI agentic loop."""

import re
import time
from typing import Optional, Tuple
from playwright.sync_api import Page, TimeoutError as PWTimeout

from src.config.constants import (
    LEETCODE_PROBLEM, LEETCODE_EDITOR,
    TIMEOUT_SHORT, TIMEOUT_MEDIUM, TIMEOUT_LONG,
)
from src.leetcode.solutions import LeetCodeSolutionScraper
from src.ai.solver import AIAgent, TestResult
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class LeetCodeSolver:
    def __init__(self, page: Page):
        from src.config.settings import settings
        self._page = page
        self.settings = settings
        self.scraper = LeetCodeSolutionScraper(page)
        self.ai = AIAgent()

    @property
    def page(self) -> Page:
        return self._page

    @page.setter
    def page(self, value: Page):
        """Keep scraper in sync whenever the active tab changes."""
        self._page = value
        if hasattr(self, 'scraper'):
            self.scraper.page = value

    # ── public ─────────────────────────────────────────────────────────────────

    def solve_current_problem(self) -> bool:
        """
        Agentic solve loop:
          1. Save problem URL + extract title/slug for AI context.
          2. Try web scraping for a Java solution.
          3. If scraping fails → Phase 1: AI generates solution.
          4. Inject code → Run test → check result (structured TestResult).
          5. If tests fail → Phase 2: AI debug loop (up to ai_max_debug_cycles).
          6. If debug exhausted → Phase 3: AI escalation (new algorithm).
          7. Submit only after tests pass.
        """
        self.page.wait_for_load_state("load")
        self.page.wait_for_timeout(1_500)

        problem_url = self.page.url
        slug = _slug_from_url(problem_url)
        title = _title_from_slug(slug)
        logger.info(f"On LeetCode: {problem_url}  (slug={slug!r})")

        # ── Phase 1: Code Acquisition ──────────────────────────────────────────
        code = self._acquire_code(title, slug, problem_url)
        if not code:
            logger.error(f"[AGENT] Could not acquire any code for '{title}' — skipping")
            return False

        # Navigate back to editor (scraper may have navigated away)
        logger.info(f"Returning to problem editor: {problem_url}")
        self._safe_goto(problem_url)

        # Wait extra for Monaco to fully initialize after navigation
        self.page.wait_for_timeout(2_000)

        switched = self._switch_language_to_java()
        if not switched:
            logger.warning("[AGENT] Language may not be Java — injecting anyway, but expect issues")

        # Give editor a moment to reinitialize after language switch
        self.page.wait_for_timeout(1_000)

        if not self._enter_code(code):
            logger.error("[AGENT] Code injection failed")
            return False

        # ── Phase 2: Test → Debug loop ─────────────────────────────────────────
        current_code = code
        for cycle in range(1, self.settings.ai_max_debug_cycles + 2):
            logger.info(f"[AGENT] Attempt {cycle} — running sample tests…")
            result = self._run_code_and_check()

            if result.passed:
                logger.info("[AGENT] Sample tests passed — submitting ✅")
                return self._submit_and_wait()

            logger.warning(
                f"[AGENT] Attempt {cycle} failed — "
                f"{result.error_type}: {result.error_message[:120]}"
            )

            if cycle > self.settings.ai_max_debug_cycles:
                logger.error("[AGENT] All debug cycles exhausted — skipping problem")
                return False

            # Phase 3: escalate on last debug cycle
            if cycle == self.settings.ai_max_debug_cycles:
                logger.warning("[AGENT] Max debug cycles reached — escalating to new algorithm")
                fixed = self.ai.escalate(title, current_code, result)
            else:
                fixed = self.ai.debug(title, current_code, result)

            if not fixed:
                logger.error("[AGENT] AI returned no code — aborting")
                return False

            fixed = _strip_markdown(fixed)
            current_code = fixed
            logger.info(f"[AGENT] Injecting AI-fixed code ({len(fixed)} chars)…")
            if not self._enter_code(fixed):
                logger.error("[AGENT] Code re-injection failed")
                return False

            time.sleep(self.settings.retry_delay)

        return False

    # ── code acquisition ───────────────────────────────────────────────────────

    def _acquire_code(self, title: str, slug: str, problem_url: str) -> Optional[str]:
        """
        Try scraping first. If scraping returns nothing, use AI to generate.
        Returns validated Java code or None.
        """
        logger.info("[AGENT] Phase 1 — trying web scraping…")
        code = self.scraper.get_best_solution()
        if code:
            code = _strip_markdown(code)
            logger.info(f"[AGENT] Scraping succeeded ({len(code)} chars) ✅")
            return code

        logger.warning("[AGENT] Scraping returned no valid Java code — invoking AI generator")

        # Read problem description from the editor page for AI context
        description = self._read_problem_description(problem_url)

        ai_code = self.ai.generate(title, slug, description)
        if ai_code:
            return _strip_markdown(ai_code)

        logger.error("[AGENT] AI generation also failed")
        return None

    def _read_problem_description(self, problem_url: str) -> str:
        """Navigate to problem page and scrape the description text for AI context."""
        try:
            self._safe_goto(problem_url)
            # LeetCode problem description lives in a div with data-track-load
            for sel in [
                "[data-track-load='description_content']",
                ".elfjS",                     # older layout class
                "div[class*='description']",
            ]:
                try:
                    el = self.page.locator(sel).first
                    el.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
                    text = el.inner_text().strip()
                    if text:
                        logger.debug(f"Problem description scraped ({len(text)} chars)")
                        return text[:3000]  # cap to avoid giant prompts
                except PWTimeout:
                    continue
        except Exception as e:
            logger.warning(f"Could not read problem description: {e}")
        # Fallback: title is enough for the AI
        return "(description unavailable — solve based on the problem title)"

    # ── navigation helpers ─────────────────────────────────────────────────────

    def _safe_goto(self, url: str, retries: int = 3):
        """Navigate with retry on network errors."""
        for attempt in range(retries):
            try:
                self.page.goto(url)
                self.page.wait_for_load_state("load")
                self.page.wait_for_timeout(1_500)
                return
            except Exception as e:
                if attempt < retries - 1:
                    logger.warning(f"Navigation failed (attempt {attempt+1}/{retries}): {e} — retrying")
                    time.sleep(2)
                else:
                    logger.error(f"Navigation failed after {retries} attempts: {e}")
                    raise

    def _switch_language_to_java(self):
        """
        Ensure the Monaco editor language is set to Java before injecting code.
        Strategy:
          1. Read what language is currently shown on the language button.
          2. If already Java → done.
          3. Otherwise open the dropdown and click the Java option.
          4. Verify the switch succeeded; retry once if not.
        """
        for attempt in range(3):
            current = self._get_current_language()
            if current and "java" in current.lower() and "javascript" not in current.lower():
                logger.info(f"Editor language already Java ✅ (was: {current!r})")
                return True

            logger.info(
                f"[lang] Current language: {current!r} — switching to Java (attempt {attempt+1}/3)"
            )

            if self._open_language_dropdown_and_pick_java():
                self.page.wait_for_timeout(800)
                verify = self._get_current_language()
                if verify and "java" in verify.lower() and "javascript" not in verify.lower():
                    logger.info(f"Switched to Java ✅ (confirmed: {verify!r})")
                    return True
                logger.warning(f"Switch appeared to work but language is still {verify!r} — retrying")
            else:
                logger.warning(f"Could not open language dropdown (attempt {attempt+1}/3)")

            self.page.wait_for_timeout(1_000)

        logger.error("Failed to switch editor to Java after 3 attempts — code may be injected into wrong language")
        return False

    def _get_current_language(self) -> str:
        """
        Read the currently selected language label from the editor toolbar.
        Returns lowercase string like 'c++', 'java', 'python3', or '' if not found.
        """
        # LeetCode renders the language picker as a button whose text IS the language name
        selectors = [
            # New UI: headlessui button in the toolbar
            "[data-mode-id]",                         # Monaco editor attribute
            "button[id^='headlessui-listbox-button']",
            # Older / fallback selectors
            "[class*='lang-select'] button",
            "[class*='language'] button",
            "button[aria-haspopup='listbox']",
            "button[aria-haspopup='true']",
        ]
        for sel in selectors:
            try:
                els = self.page.locator(sel).all()
                for el in els:
                    try:
                        txt = el.inner_text(timeout=400).strip()
                        if txt and len(txt) < 30 and not txt.isdigit():
                            # Filter out non-language buttons (Submit, Run, etc.)
                            known_langs = [
                                "c++", "java", "python", "javascript", "typescript",
                                "c", "c#", "go", "ruby", "swift", "kotlin", "rust",
                                "scala", "php", "mysql", "mssql", "bash",
                            ]
                            if any(lang in txt.lower() for lang in known_langs):
                                return txt
                    except Exception:
                        continue
            except Exception:
                continue

        # Last resort: read Monaco's language ID via JS
        try:
            lang_id = self.page.evaluate(
                """() => {
                    try {
                        const models = monaco.editor.getModels();
                        if (models && models.length > 0) return models[0].getLanguageId();
                    } catch(e) {}
                    return null;
                }"""
            )
            if lang_id:
                return str(lang_id)
        except Exception:
            pass

        return ""

    def _open_language_dropdown_and_pick_java(self) -> bool:
        """
        Click the language picker button to open the dropdown, then click Java.
        Returns True if Java option was clicked.
        """
        # Selectors for the language dropdown trigger button
        dropdown_trigger_selectors = [
            "button[id^='headlessui-listbox-button']",
            "[class*='lang-select'] button",
            "[class*='language'] button",
            "button[aria-haspopup='listbox']",
            "button[aria-haspopup='true']",
        ]

        opened = False
        for sel in dropdown_trigger_selectors:
            try:
                btns = self.page.locator(sel).all()
                for btn in btns:
                    try:
                        txt = btn.inner_text(timeout=400).strip().lower()
                        # Must be a language button, not Submit/Run
                        if any(lang in txt for lang in ["c++", "java", "python", "c", "go", "ruby", "swift"]):
                            btn.click()
                            self.page.wait_for_timeout(600)
                            opened = True
                            break
                    except Exception:
                        continue
                if opened:
                    break
            except Exception:
                continue

        if not opened:
            return False

        # Now pick Java from the opened dropdown
        java_option_selectors = [
            # Exact match first to avoid matching "JavaScript"
            "li[role='option']:has-text('Java')",
            "[role='option']:has-text('Java')",
            "li:has-text('Java')",
        ]
        for sel in java_option_selectors:
            try:
                # Filter strictly: text must be exactly "Java" not "JavaScript"
                opts = self.page.locator(sel).all()
                for opt in opts:
                    try:
                        txt = opt.inner_text(timeout=400).strip()
                        if txt.lower() == "java":  # exact match only
                            opt.click()
                            logger.debug(f"Clicked Java option in dropdown ✅")
                            return True
                    except Exception:
                        continue
            except Exception:
                continue

        # Fallback: use keyboard — type "Java" in the dropdown search if it has one
        try:
            self.page.keyboard.type("Java")
            self.page.wait_for_timeout(300)
            java_opt = self.page.locator("[role='option']:has-text('Java')").first
            java_opt.wait_for(state="visible", timeout=TIMEOUT_SHORT)
            java_opt.click()
            return True
        except Exception:
            pass

        logger.warning("Java option not found in the language dropdown")
        return False

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

    def _run_code_and_check(self) -> TestResult:
        """
        Click Run, wait for the test result panel, and return a structured TestResult.
        Captures error type, message, expected vs actual for the AI debug agent.
        """
        run_selectors = [
            "[data-e2e-locator='console-run-button']",
            "button:has-text('Run')",
        ]
        run_clicked = False
        for sel in run_selectors:
            try:
                btn = self.page.locator(sel).first
                btn.wait_for(state="visible", timeout=TIMEOUT_SHORT)
                btn.click()
                run_clicked = True
                logger.info("Clicked Run button ✅")
                break
            except PWTimeout:
                continue

        if not run_clicked:
            logger.warning("Run button not found — will submit directly")
            return TestResult(passed=True)  # allow submit if Run can't be found

        FAIL_INDICATORS = [
            "Wrong Answer", "Runtime Error", "Time Limit Exceeded",
            "Compile Error", "Memory Limit Exceeded", "Output Limit Exceeded",
        ]

        logger.info("Waiting for test result…")
        for _ in range(40):  # up to 40s
            self.page.wait_for_timeout(1_000)
            try:
                page_text = self.page.evaluate("() => document.body.innerText")

                # ── PASS ──────────────────────────────────────────────────────
                if "Accepted" in page_text and "Runtime" in page_text:
                    logger.info("Test Result: Accepted ✅")
                    return TestResult(passed=True)

                # ── FAIL — extract rich context for AI debug agent ─────────────
                for fail in FAIL_INDICATORS:
                    if fail in page_text:
                        error_msg, expected, actual = _parse_error_context(page_text, fail)
                        logger.warning(
                            f"Test Result: {fail} | "
                            f"expected={expected!r:.60} | actual={actual!r:.60}"
                        )
                        return TestResult(
                            passed=False,
                            error_type=fail,
                            error_message=error_msg,
                            expected=expected,
                            actual=actual,
                        )
            except Exception:
                pass

        logger.warning("Test result: timed out waiting for response")
        return TestResult(passed=False, error_type="Timeout", error_message="Test result timed out after 40s")

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

        # Wait for the submission result panel to appear (specific selector only)
        result_sel = "[data-e2e-locator='submission-result']"
        try:
            result_el = self.page.locator(result_sel).first
            result_el.wait_for(state="visible", timeout=TIMEOUT_LONG)
            result_text = result_el.inner_text().strip()
            logger.info(f"Submission result: {result_text}")
            return "Accepted" in result_text
        except PWTimeout:
            # Fallback: check for accepted-specific CSS class (no broad text match)
            for sel in LEETCODE_EDITOR["result_accepted_fallback"]:
                try:
                    self.page.locator(sel).first.wait_for(state="visible", timeout=3_000)
                    return True
                except PWTimeout:
                    continue
            logger.warning("No submission result detected within timeout")
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


def _slug_from_url(url: str) -> str:
    """Extract problem slug from a LeetCode URL."""
    m = re.search(r'/problems/([^/?#]+)', url)
    return m.group(1) if m else "unknown"


def _title_from_slug(slug: str) -> str:
    """Convert slug like 'two-sum' → 'Two Sum'."""
    return slug.replace("-", " ").title()


def _parse_error_context(page_text: str, error_type: str) -> Tuple[str, str, str]:
    """
    Extract error message, expected output, and actual output from the page text.
    LeetCode renders these as labelled lines in the console panel.
    """
    lines = page_text.splitlines()

    # Find the block starting at or near the error type
    error_start = next(
        (i for i, l in enumerate(lines) if error_type in l), None
    )
    error_block = lines[error_start: error_start + 30] if error_start is not None else lines

    error_msg = ""
    expected = ""
    actual = ""

    for i, line in enumerate(error_block):
        l = line.strip()
        if not error_msg and error_type in l:
            error_msg = l
        elif re.match(r"(?i)^expected", l):
            # Next non-empty line is the value
            for j in range(i + 1, min(i + 4, len(error_block))):
                v = error_block[j].strip()
                if v:
                    expected = v
                    break
        elif re.match(r"(?i)^(output|actual)", l):
            for j in range(i + 1, min(i + 4, len(error_block))):
                v = error_block[j].strip()
                if v:
                    actual = v
                    break

    # Cap lengths so prompts stay reasonable
    return error_msg[:500], expected[:300], actual[:300]
