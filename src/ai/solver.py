"""
Agentic AI solver — three-phase loop using OpenRouter (minimax/minimax-m2.5).

Phase 1 — CODE ACQUISITION: Called when web scraping returns no valid solution.
           AI generates a Java solution from the problem title + description.

Phase 2 — DEBUG AGENT: Called when tests fail. Receives (code, error_type,
           error_message, expected, actual) and returns a fixed version.

Phase 3 — ESCALATION: Called after max debug cycles. AI rewrites from scratch
           with an explicit hint to try a completely different algorithm.
"""

import re
import time
from dataclasses import dataclass
from typing import Optional

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# ── Prompts ────────────────────────────────────────────────────────────────────

_SYSTEM = (
    "You are an expert competitive programmer specializing in Java. "
    "You ONLY output raw Java code — no markdown fences (``` or ```java), "
    "no prose, no comments unless they are inside the code itself. "
    "The code must be a complete, self-contained LeetCode solution class "
    "that compiles and runs correctly on LeetCode's Java 17 judge."
)

_GENERATE_TMPL = """\
Solve the following LeetCode problem in Java.

Problem title: {title}
Problem slug:  {slug}
Description:
{description}

Rules:
- Return ONLY the Java class (e.g. class Solution {{ ... }})
- Use the exact method signature LeetCode expects
- Optimize for correctness first, then efficiency
- No imports unless strictly needed (java.util.* is fine)
"""

_DEBUG_TMPL = """\
The following Java solution for the LeetCode problem "{title}" failed with:

Error type   : {error_type}
Error message: {error_message}
Expected     : {expected}
Actual output: {actual}

Here is the current code:
{code}

Fix the bug and return ONLY the corrected Java class.
Do not explain anything — just return the fixed code.
"""

_ESCALATE_TMPL = """\
All previous attempts to fix the Java solution for "{title}" have failed.
The last error was:

Error type   : {error_type}
Error message: {error_message}

Here is the broken code:
{code}

Discard this approach completely. Write a brand-new Java solution using a
DIFFERENT algorithm or data structure strategy. Return ONLY the Java class.
"""

# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class TestResult:
    """Structured result from a LeetCode test/submit run."""
    passed: bool
    error_type: str = ""        # "Wrong Answer", "Runtime Error", "Compile Error", etc.
    error_message: str = ""     # Raw error text from LeetCode
    expected: str = ""          # Expected output (if shown)
    actual: str = ""            # Actual output (if shown)

    def to_debug_context(self) -> str:
        return (
            f"error_type={self.error_type!r} "
            f"error_message={self.error_message!r} "
            f"expected={self.expected!r} "
            f"actual={self.actual!r}"
        )


# ── Main agent ─────────────────────────────────────────────────────────────────

class AIAgent:
    """
    Agentic loop:
      1. generate(title, slug, description) → Java code
      2. debug(title, code, test_result)    → fixed Java code
      3. escalate(title, code, test_result) → completely new Java code
    """

    _MAX_API_RETRIES = 3
    _RETRY_BASE_DELAY = 2  # seconds, doubles each attempt

    def __init__(self):
        from src.config.settings import settings
        self.settings = settings
        self._client = None
        self._provider = settings.llm_provider  # "openrouter" by default

    # ── public API ─────────────────────────────────────────────────────────────

    def generate(self, title: str, slug: str, description: str) -> Optional[str]:
        """Phase 1: Generate a Java solution from scratch."""
        prompt = _GENERATE_TMPL.format(
            title=title, slug=slug, description=description
        )
        logger.info(f"[AI] Generating solution for '{title}' via {self.settings.llm_model}")
        code = self._call_with_retry(prompt)
        if code:
            code = _strip_fences(code)
            logger.info(f"[AI] Generated {len(code)} chars ✅")
        return code

    def debug(self, title: str, code: str, result: TestResult) -> Optional[str]:
        """Phase 2: Fix a failing solution given the test result context."""
        prompt = _DEBUG_TMPL.format(
            title=title,
            error_type=result.error_type,
            error_message=result.error_message,
            expected=result.expected,
            actual=result.actual,
            code=code,
        )
        logger.info(
            f"[AI] Debug cycle for '{title}' — "
            f"error: {result.error_type or result.error_message[:60]}"
        )
        fixed = self._call_with_retry(prompt)
        if fixed:
            fixed = _strip_fences(fixed)
            logger.info(f"[AI] Debug produced {len(fixed)} chars ✅")
        return fixed

    def escalate(self, title: str, code: str, result: TestResult) -> Optional[str]:
        """Phase 3: Give up on current approach, ask for a brand-new algorithm."""
        prompt = _ESCALATE_TMPL.format(
            title=title,
            error_type=result.error_type,
            error_message=result.error_message,
            code=code,
        )
        logger.warning(f"[AI] ESCALATING for '{title}' — requesting new algorithm")
        new_code = self._call_with_retry(prompt)
        if new_code:
            new_code = _strip_fences(new_code)
            logger.info(f"[AI] Escalated solution: {len(new_code)} chars ✅")
        return new_code

    # ── internal ───────────────────────────────────────────────────────────────

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            if self._provider == "openrouter":
                self._client = OpenAI(
                    api_key=self.settings.openrouter_api_key,
                    base_url=self.settings.openrouter_base_url,
                    default_headers={
                        "HTTP-Referer": "https://github.com/bytes-bot",
                        "X-Title": "BytsOne Automation Bot",
                    },
                )
            else:
                # Standard OpenAI (fallback)
                self._client = OpenAI(api_key=self.settings.openai_api_key)
        return self._client

    def _call_with_retry(self, prompt: str) -> Optional[str]:
        for attempt in range(1, self._MAX_API_RETRIES + 1):
            try:
                return self._call_llm(prompt)
            except Exception as e:
                wait = self._RETRY_BASE_DELAY * (2 ** (attempt - 1))
                if attempt < self._MAX_API_RETRIES:
                    logger.warning(
                        f"[AI] API error (attempt {attempt}/{self._MAX_API_RETRIES}): "
                        f"{e} — retrying in {wait}s"
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        f"[AI] API failed after {self._MAX_API_RETRIES} attempts: {e}"
                    )
        return None

    def _call_llm(self, prompt: str) -> str:
        if self._provider in ("openrouter", "openai"):
            return self._call_openai_compat(prompt)
        elif self._provider == "anthropic":
            return self._call_anthropic(prompt)
        raise ValueError(f"Unknown provider: {self._provider}")

    def _call_openai_compat(self, prompt: str) -> str:
        client = self._get_client()
        model = (
            self.settings.openrouter_model
            if self._provider == "openrouter"
            else self.settings.openai_model
        )
        temperature = self.settings.llm_temperature
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=4096,
        )
        result = response.choices[0].message.content
        if result is None:
            raise ValueError("LLM returned empty content")
        return result.strip()

    def _call_anthropic(self, prompt: str) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        message = client.messages.create(
            model=self.settings.anthropic_model,
            max_tokens=4096,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()


# ── helpers ────────────────────────────────────────────────────────────────────

def _strip_fences(code: str) -> str:
    """Remove markdown code fences the LLM may have added despite instructions."""
    code = re.sub(r"^```[\w]*\n?", "", code, flags=re.MULTILINE)
    code = re.sub(r"\n?```$", "", code, flags=re.MULTILINE)
    return code.strip()

