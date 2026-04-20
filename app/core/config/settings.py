from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="resume-agent", alias="APP_NAME")
    app_env: str = Field(default="dev", alias="APP_ENV")
    app_debug: bool = Field(default=True, alias="APP_DEBUG")
    app_log_level: str = Field(default="INFO", alias="APP_LOG_LEVEL")
    api_prefix: str = Field(default="/api/v1", alias="API_PREFIX")

    llm_enabled: bool = Field(default=False, alias="LLM_ENABLED")
    llm_base_url: str = Field(default="", alias="LLM_BASE_URL")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model_name: str = Field(default="", alias="LLM_MODEL_NAME")
    llm_temperature: float = Field(default=0.1, alias="LLM_TEMPERATURE")

    postgres_dsn: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:54329/resume_agent",
        alias="POSTGRES_DSN",
    )
    sqlalchemy_echo: bool = Field(default=False, alias="SQLALCHEMY_ECHO")
    db_pool_size: int = Field(default=10, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, alias="DB_MAX_OVERFLOW")

    max_upload_size_mb: int = Field(default=20, alias="MAX_UPLOAD_SIZE_MB")
    ocr_enabled: bool = Field(default=False, alias="OCR_ENABLED")
    ocr_provider: str = Field(default="mineru", alias="OCR_PROVIDER")
    ocr_base_url: str = Field(default="", alias="OCR_BASE_URL")
    resume_parse_timeout_sec: int = Field(default=60, alias="RESUME_PARSE_TIMEOUT_SEC")
    file_root_dir: str = Field(default="./data", alias="FILE_ROOT_DIR")
    artifact_root_dir: str = Field(default="./data/tasks", alias="ARTIFACT_ROOT_DIR")

    top_k: int = Field(default=20, alias="TOP_K")
    vector_recall_k: int = Field(default=50, alias="VECTOR_RECALL_K")
    keyword_recall_k: int = Field(default=50, alias="KEYWORD_RECALL_K")
    score_weight_skill: float = Field(default=0.35, alias="SCORE_WEIGHT_SKILL")
    score_weight_experience: float = Field(default=0.25, alias="SCORE_WEIGHT_EXPERIENCE")
    score_weight_project: float = Field(default=0.20, alias="SCORE_WEIGHT_PROJECT")
    score_weight_education: float = Field(default=0.10, alias="SCORE_WEIGHT_EDUCATION")
    score_weight_preference: float = Field(default=0.10, alias="SCORE_WEIGHT_PREFERENCE")
    task_max_retries: int = Field(default=2, alias="TASK_MAX_RETRIES")
    task_stage_timeout_sec: int = Field(default=180, alias="TASK_STAGE_TIMEOUT_SEC")
    task_lock_timeout_sec: int = Field(default=600, alias="TASK_LOCK_TIMEOUT_SEC")
    task_worker_poll_interval_sec: int = Field(default=2, alias="TASK_WORKER_POLL_INTERVAL_SEC")

    cors_origins_raw: str = Field(default="", alias="CORS_ORIGINS")
    rate_limit_enabled: bool = Field(default=False, alias="RATE_LIMIT_ENABLED")
    request_id_enabled: bool = Field(default=True, alias="REQUEST_ID_ENABLED")
    audit_log_enabled: bool = Field(default=True, alias="AUDIT_LOG_ENABLED")

    auth_enabled: bool = Field(default=False, alias="AUTH_ENABLED")
    jwt_secret: str = Field(default="dev-secret", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    admin_token: str = Field(default="admin-token", alias="ADMIN_TOKEN")
    auto_seed_jobs: bool = Field(default=True, alias="AUTO_SEED_JOBS")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins(self) -> list[str]:
        if not self.cors_origins_raw:
            return ["*"]
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def file_root_path(self) -> Path:
        return Path(self.file_root_dir).resolve()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def artifact_root_path(self) -> Path:
        return Path(self.artifact_root_dir).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
