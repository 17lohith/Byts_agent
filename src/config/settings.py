"""Configuration settings loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator, model_validator
from typing import Optional


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # BytsOne Configuration
    bytesone_url: str = "https://www.bytsone.com/home/courses"

    # Which courses to process — comma-separated: "class_problems,task_problems"
    # Order matters: first listed = processed first
    courses_order: str = "class_problems,task_problems"

    # Account emails — used to pick the right Google account on login
    bytesone_email: str = ""   # Karunya institutional email
    leetcode_email: str = ""   # Personal Gmail

    @property
    def courses_list(self) -> list:
        return [c.strip() for c in self.courses_order.split(",") if c.strip()]

    # LLM Provider Configuration
    llm_provider: str = "openai"
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None

    # OpenAI Settings
    openai_model: str = "gpt-4-turbo"
    openai_temperature: float = Field(default=0.2, ge=0.0, le=2.0)

    # Anthropic Settings
    anthropic_model: str = "claude-3-5-sonnet-20241022"
    anthropic_temperature: float = Field(default=0.2, ge=0.0, le=2.0)

    # Browser Settings
    slow_mo: int = Field(default=100, ge=0)
    headless: bool = False          # Always headed so you can see + interact on first run
    browser_profile_dir: str = "browser_profile"  # Persistent Chromium profile

    # Session Management
    session_file: str = "storage_state.json"
    progress_file: str = "progress.json"

    # Automation Settings
    max_retries: int = Field(default=3, gt=0)
    retry_delay: int = Field(default=2, gt=0)
    page_timeout: int = Field(default=30_000, gt=0)
    navigation_timeout: int = Field(default=60_000, gt=0)
    login_wait_timeout: int = Field(default=300_000, gt=0)  # 5 min for manual login

    # Logging
    log_level: str = "INFO"
    log_file: str = "logs/automation.log"

    @field_validator("llm_provider")
    @classmethod
    def validate_llm_provider(cls, v: str) -> str:
        allowed = {"openai", "anthropic"}
        if v not in allowed:
            raise ValueError(f"llm_provider must be one of {allowed}, got '{v}'")
        return v

    @model_validator(mode="after")
    def validate_api_key_present(self) -> "Settings":
        # LLM is not used in the current flow (Solutions tab replaces it).
        # Skip API key validation to avoid blocking users who haven't set one.
        return self

    @property
    def llm_api_key(self) -> Optional[str]:
        if self.llm_provider == "openai":
            return self.openai_api_key
        return self.anthropic_api_key

    @property
    def llm_model(self) -> str:
        if self.llm_provider == "openai":
            return self.openai_model
        return self.anthropic_model

    @property
    def llm_temperature(self) -> float:
        if self.llm_provider == "openai":
            return self.openai_temperature
        return self.anthropic_temperature


try:
    settings = Settings()
except Exception as _e:
    import sys
    print(f"\n[CONFIG ERROR] {_e}\nCopy .env.example → .env and fill in your values.\n")
    sys.exit(1)
