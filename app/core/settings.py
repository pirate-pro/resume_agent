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
        default=120.0,
        validation_alias=AliasChoices("LLM_TIMEOUT_SECONDS", "VL_MODEL_TIMEOUT_SECONDS"),
    )
    maintenance_llm_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MAINTENANCE_LLM_BASE_URL"),
    )
    maintenance_llm_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MAINTENANCE_LLM_API_KEY"),
    )
    maintenance_llm_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MAINTENANCE_LLM_MODEL"),
    )
    maintenance_llm_timeout_seconds: float | None = Field(
        default=None,
        validation_alias=AliasChoices("MAINTENANCE_LLM_TIMEOUT_SECONDS"),
    )
    chat_stream_heartbeat_interval_seconds: float = Field(
        default=15.0,
        validation_alias=AliasChoices("CHAT_STREAM_HEARTBEAT_INTERVAL_SECONDS"),
    )
    chat_stream_run_timeout_seconds: float = Field(
        default=300.0,
        validation_alias=AliasChoices("CHAT_STREAM_RUN_TIMEOUT_SECONDS"),
    )
    mid_term_flush_worker_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("MID_TERM_FLUSH_WORKER_ENABLED"),
    )
    mid_term_flush_worker_poll_interval_seconds: float = Field(
        default=8.0,
        validation_alias=AliasChoices("MID_TERM_FLUSH_WORKER_POLL_INTERVAL_SECONDS"),
    )
    mid_term_flush_worker_max_agents_per_tick: int = Field(
        default=24,
        validation_alias=AliasChoices("MID_TERM_FLUSH_WORKER_MAX_AGENTS_PER_TICK"),
    )
    mid_term_flush_worker_max_jobs_per_agent: int = Field(
        default=2,
        validation_alias=AliasChoices("MID_TERM_FLUSH_WORKER_MAX_JOBS_PER_AGENT"),
    )
    mid_term_flush_model_context_window_tokens: int = Field(
        default=32768,
        validation_alias=AliasChoices("MID_TERM_FLUSH_MODEL_CONTEXT_WINDOW_TOKENS"),
    )
    mid_term_flush_input_ratio: float = Field(
        default=0.35,
        validation_alias=AliasChoices("MID_TERM_FLUSH_INPUT_RATIO"),
    )
    mid_term_flush_output_reserve_tokens: int = Field(
        default=1200,
        validation_alias=AliasChoices("MID_TERM_FLUSH_OUTPUT_RESERVE_TOKENS"),
    )
    mid_term_flush_prompt_overhead_tokens: int = Field(
        default=900,
        validation_alias=AliasChoices("MID_TERM_FLUSH_PROMPT_OVERHEAD_TOKENS"),
    )
    mid_term_flush_max_input_tokens: int = Field(
        default=5200,
        validation_alias=AliasChoices("MID_TERM_FLUSH_MAX_INPUT_TOKENS"),
    )
    context_compaction_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("CONTEXT_COMPACTION_ENABLED"),
    )
    context_compaction_trigger_event_count: int = Field(
        default=60,
        validation_alias=AliasChoices("CONTEXT_COMPACTION_TRIGGER_EVENT_COUNT"),
    )
    context_compaction_trigger_token_count: int = Field(
        default=12000,
        validation_alias=AliasChoices("CONTEXT_COMPACTION_TRIGGER_TOKEN_COUNT"),
    )
    context_compaction_trigger_context_window_ratio: float = Field(
        default=0.45,
        validation_alias=AliasChoices("CONTEXT_COMPACTION_TRIGGER_CONTEXT_WINDOW_RATIO"),
    )
    context_compaction_model_context_window_tokens: int = Field(
        default=32768,
        validation_alias=AliasChoices("CONTEXT_COMPACTION_MODEL_CONTEXT_WINDOW_TOKENS"),
    )
    context_compaction_retention_strategy: str = Field(
        default="event_count",
        validation_alias=AliasChoices("CONTEXT_COMPACTION_RETENTION_STRATEGY"),
    )
    context_compaction_retain_event_count: int = Field(
        default=32,
        validation_alias=AliasChoices("CONTEXT_COMPACTION_RETAIN_EVENT_COUNT"),
    )
    context_compaction_retain_token_count: int = Field(
        default=7000,
        validation_alias=AliasChoices("CONTEXT_COMPACTION_RETAIN_TOKEN_COUNT"),
    )
    context_compaction_retain_context_window_ratio: float = Field(
        default=0.25,
        validation_alias=AliasChoices("CONTEXT_COMPACTION_RETAIN_CONTEXT_WINDOW_RATIO"),
    )
    context_compaction_model_input_ratio: float = Field(
        default=0.45,
        validation_alias=AliasChoices("CONTEXT_COMPACTION_MODEL_INPUT_RATIO"),
    )
    context_compaction_model_output_reserve_tokens: int = Field(
        default=1600,
        validation_alias=AliasChoices("CONTEXT_COMPACTION_MODEL_OUTPUT_RESERVE_TOKENS"),
    )
    context_compaction_prompt_overhead_tokens: int = Field(
        default=900,
        validation_alias=AliasChoices("CONTEXT_COMPACTION_PROMPT_OVERHEAD_TOKENS"),
    )

    @field_validator("app_name", "llm_base_url", "llm_api_key", "llm_model")
    @classmethod
    def _validate_non_empty_string(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValidationError("Configuration string value cannot be empty.")
        return value.strip()

    @field_validator("maintenance_llm_base_url", "maintenance_llm_api_key", "maintenance_llm_model")
    @classmethod
    def _validate_optional_non_empty_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

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

    @field_validator("maintenance_llm_timeout_seconds")
    @classmethod
    def _validate_optional_timeout(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value <= 0:
            raise ValidationError("MAINTENANCE_LLM_TIMEOUT_SECONDS must be positive.")
        return value

    @field_validator("chat_stream_heartbeat_interval_seconds")
    @classmethod
    def _validate_chat_stream_heartbeat_interval(cls, value: float) -> float:
        if value <= 0:
            raise ValidationError("CHAT_STREAM_HEARTBEAT_INTERVAL_SECONDS must be positive.")
        return value

    @field_validator("chat_stream_run_timeout_seconds")
    @classmethod
    def _validate_chat_stream_run_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValidationError("CHAT_STREAM_RUN_TIMEOUT_SECONDS must be positive.")
        return value

    @field_validator("mid_term_flush_worker_enabled", mode="before")
    @classmethod
    def _validate_mid_term_flush_worker_enabled(cls, value: bool | str) -> bool:
        return _parse_bool(value, field_name="MID_TERM_FLUSH_WORKER_ENABLED")

    @field_validator("context_compaction_enabled", mode="before")
    @classmethod
    def _validate_context_compaction_enabled(cls, value: bool | str) -> bool:
        return _parse_bool(value, field_name="CONTEXT_COMPACTION_ENABLED")

    @field_validator("context_compaction_retention_strategy")
    @classmethod
    def _validate_context_compaction_retention_strategy(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"event_count", "token_count", "context_ratio"}:
            raise ValidationError("CONTEXT_COMPACTION_RETENTION_STRATEGY must be event_count/token_count/context_ratio.")
        return normalized

    @field_validator(
        "context_compaction_trigger_context_window_ratio",
        "context_compaction_retain_context_window_ratio",
        "context_compaction_model_input_ratio",
    )
    @classmethod
    def _validate_context_compaction_ratio(cls, value: float) -> float:
        if value <= 0 or value >= 1:
            raise ValidationError("CONTEXT_COMPACTION_*_RATIO values must be in (0,1).")
        return value

    @field_validator(
        "context_compaction_trigger_event_count",
        "context_compaction_trigger_token_count",
        "context_compaction_model_context_window_tokens",
        "context_compaction_retain_event_count",
        "context_compaction_retain_token_count",
        "context_compaction_model_output_reserve_tokens",
        "context_compaction_prompt_overhead_tokens",
    )
    @classmethod
    def _validate_context_compaction_positive_ints(cls, value: int) -> int:
        if value <= 0:
            raise ValidationError("CONTEXT_COMPACTION_* integer values must be positive.")
        return value

    @field_validator("mid_term_flush_worker_poll_interval_seconds")
    @classmethod
    def _validate_mid_term_flush_worker_poll_interval(cls, value: float) -> float:
        if value <= 0:
            raise ValidationError("MID_TERM_FLUSH_WORKER_POLL_INTERVAL_SECONDS must be positive.")
        return value

    @field_validator("mid_term_flush_worker_max_agents_per_tick", "mid_term_flush_worker_max_jobs_per_agent")
    @classmethod
    def _validate_positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValidationError("MID_TERM_FLUSH_WORKER_* values must be positive.")
        return value

    @field_validator(
        "mid_term_flush_model_context_window_tokens",
        "mid_term_flush_output_reserve_tokens",
        "mid_term_flush_prompt_overhead_tokens",
        "mid_term_flush_max_input_tokens",
    )
    @classmethod
    def _validate_mid_term_positive_ints(cls, value: int) -> int:
        if value <= 0:
            raise ValidationError("MID_TERM_FLUSH_*_TOKENS values must be positive.")
        return value

    @field_validator("mid_term_flush_input_ratio")
    @classmethod
    def _validate_mid_term_input_ratio(cls, value: float) -> float:
        if value <= 0 or value >= 1:
            raise ValidationError("MID_TERM_FLUSH_INPUT_RATIO must be in (0,1).")
        return value

    @field_validator("mid_term_flush_max_input_tokens")
    @classmethod
    def _validate_mid_term_max_input_tokens(cls, value: int) -> int:
        if value < 512:
            raise ValidationError("MID_TERM_FLUSH_MAX_INPUT_TOKENS must be at least 512.")
        return value

    @classmethod
    def load(cls) -> "Settings":
        """Load settings from environment and .env."""
        return cls()


def _parse_bool(value: bool | str, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enable", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disable", "disabled", ""}:
            return False
    raise ValidationError(f"{field_name} must be a boolean-like value.")
