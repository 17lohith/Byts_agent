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
    bytesone_url: str = "https://www.bytsone.com/home/dashboard"
    course_name: str = "Karunya 2028 - Product Fit- Class Problems -(16-2-2026 to 21-2-2026)"
    
    # LeetCode Configuration
    leetcode_username: str = "17lohith"
    
    # LLM Provider Configuration
    llm_provider: str = "openai"
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    
    # OpenAI Settings
    openai_model: str = "gpt-4-turbo"
    openai_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    
    # Anthropic Settings
    anthropic_model: str = "claude-3-sonnet-20240229"
    anthropic_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    
    # Browser Settings
    slow_mo: int = Field(default=100, ge=0)
    # Connect to your already-running Brave browser
    cdp_url: str = "http://127.0.0.1:9222"
    
    # Session Management
    session_file: str = "storage_state.json"
    progress_file: str = "progress.json"
    
    # Automation Settings
    max_retries: int = Field(default=3, gt=0)
    retry_delay: int = Field(default=2, gt=0)
    page_timeout: int = Field(default=30000, gt=0)
    navigation_timeout: int = Field(default=60000, gt=0)
    
    # Logging
    log_level: str = "INFO"
    log_file: str = "logs/automation.log"

    @field_validator("llm_provider")
    @classmethod
    def validate_llm_provider(cls, v: str) -> str:
        """Ensure llm_provider is one of the supported values."""
        allowed = {"openai", "anthropic"}
        if v not in allowed:
            raise ValueError(f"llm_provider must be one of {allowed}, got '{v}'")
        return v

    @model_validator(mode="after")
    def validate_api_key_present(self) -> "Settings":
        """Ensure the API key for the chosen provider is set."""
        if self.llm_provider == "openai" and not self.openai_api_key:
            raise ValueError(
                "openai_api_key must be set when llm_provider is 'openai'"
            )
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError(
                "anthropic_api_key must be set when llm_provider is 'anthropic'"
            )
        return self

    @property
    def llm_api_key(self) -> Optional[str]:
        """Get the appropriate API key based on provider."""
        if self.llm_provider == "openai":
            return self.openai_api_key
        elif self.llm_provider == "anthropic":
            return self.anthropic_api_key
        return None
    
    @property
    def llm_model(self) -> str:
        """Get the appropriate model based on provider."""
        if self.llm_provider == "openai":
            return self.openai_model
        elif self.llm_provider == "anthropic":
            return self.anthropic_model
        raise ValueError(f"Unsupported llm_provider: '{self.llm_provider}'")
    
    @property
    def llm_temperature(self) -> float:
        """Get the appropriate temperature based on provider."""
        if self.llm_provider == "openai":
            return self.openai_temperature
        elif self.llm_provider == "anthropic":
            return self.anthropic_temperature
        raise ValueError(f"Unsupported llm_provider: '{self.llm_provider}'")


# Global settings instance — fails fast with a clear message if .env is missing
try:
    settings = Settings()
except Exception as _e:
    import sys
    print(f"\n[CONFIG ERROR] {_e}\nCopy .env.example → .env and fill in your API key.\n")
    sys.exit(1)
