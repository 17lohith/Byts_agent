"""LLM-based code solver supporting OpenAI and Anthropic."""

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

SYSTEM_PROMPT = (
    "You are an expert competitive programmer. "
    "When given a LeetCode problem, respond with ONLY the complete solution code — "
    "no explanations, no markdown fences, no extra text."
)


class LLMSolver:
    def __init__(self):
        from src.config.settings import settings
        self.provider = settings.llm_provider
        self.model = settings.llm_model
        self.temperature = settings.llm_temperature
        self.api_key = settings.llm_api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            if self.provider == "openai":
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key)
            elif self.provider == "anthropic":
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def solve(self, title: str, description: str, language: str = "python3") -> str:
        """Ask the LLM to solve the problem and return only the code."""
        prompt = (
            f"Problem: {title}\n\n"
            f"{description}\n\n"
            f"Write a complete {language} solution."
        )
        logger.info(f"Sending '{title}' to {self.provider} ({self.model})")

        if self.provider == "openai":
            return self._call_openai(prompt)
        return self._call_anthropic(prompt)

    def _call_openai(self, prompt: str) -> str:
        client = self._get_client()
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=self.temperature,
        )
        return response.choices[0].message.content.strip()

    def _call_anthropic(self, prompt: str) -> str:
        client = self._get_client()
        message = client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
