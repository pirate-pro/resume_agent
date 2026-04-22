"""Application settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.errors import ValidationError

__all__ = ["Settings"]


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="single-agent-runtime", validation_alias=AliasChoices("APP_NAME"))
    debug: bool = Field(default=False, validation_alias=AliasChoices("DEBUG"))
    data_dir: Path = Field(default=Path("data"), validation_alias=AliasChoices("DATA_DIR"))
    agent_capabilities_path: Path = Field(
        default=Path("app/config/agent_capabilities.json"),
        validation_alias=AliasChoices("AGENT_CAPABILITIES_PATH"),
    )
    llm_base_url: str = Field(
        default="http://localhost:8000/v1",
        validation_alias=AliasChoices("LLM_BASE_URL", "VL_MODEL_API_URL"),
    )
    llm_api_key: str = Field(
        default="test-key",
        validation_alias=AliasChoices("LLM_API_KEY", "VL_MODEL_API_KEY"),
    )
    llm_model: str = Field(
        default="qwen3-vl-32b-instruct",
        validation_alias=AliasChoices("LLM_MODEL", "VL_MODEL_NAME"),
    )
    llm_timeout_seconds: float = Field(
        default=60.0,
        validation_alias=AliasChoices("LLM_TIMEOUT_SECONDS", "VL_MODEL_TIMEOUT_SECONDS"),
    )

    @field_validator("app_name", "llm_base_url", "llm_api_key", "llm_model")
    @classmethod
    def _validate_non_empty_string(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValidationError("Configuration string value cannot be empty.")
        return value.strip()

    @field_validator("debug", mode="before")
    @classmethod
    def _validate_debug_bool(cls, value: bool | str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", ""}:
                return False
        raise ValidationError("DEBUG must be a boolean-like value.")

    @field_validator("data_dir", "agent_capabilities_path")
    @classmethod
    def _validate_path_value(cls, value: Path) -> Path:
        raw_value = str(value).strip()
        if not raw_value:
            raise ValidationError("Path configuration cannot be empty.")
        return Path(raw_value)

    @field_validator("llm_timeout_seconds")
    @classmethod
    def _validate_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValidationError("LLM timeout must be positive.")
        return value

    @classmethod
    def load(cls) -> "Settings":
        """Load settings from environment and .env."""
        return cls()
