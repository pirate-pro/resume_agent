from pathlib import Path

from sqlalchemy import text

from app.core.config.settings import get_settings
from app.core.db.session import SessionLocal


def main() -> None:
    settings = get_settings()
    print("doctor.start")
    print(f"app_env={settings.app_env}")
    print(f"postgres_dsn={settings.postgres_dsn}")
    print(f"llm_enabled={settings.llm_enabled}")
    print(f"llm_base_url={settings.llm_base_url}")
    print(f"llm_model_name={settings.llm_model_name}")
    print(f"ocr_enabled={settings.ocr_enabled}")
    print(f"ocr_provider={settings.ocr_provider}")
    print(f"ocr_base_url={settings.ocr_base_url}")
    print(f"file_root={settings.file_root_path}")
    print(f"artifact_root={settings.artifact_root_path}")

    with SessionLocal() as session:
        session.execute(text("select 1"))
        print("database=ok")

    Path(settings.file_root_path).mkdir(parents=True, exist_ok=True)
    Path(settings.artifact_root_path).mkdir(parents=True, exist_ok=True)
    print(f"file_root_exists={Path(settings.file_root_path).is_dir()}")
    print(f"artifact_root_exists={Path(settings.artifact_root_path).is_dir()}")
    print("doctor.done")


if __name__ == "__main__":
    main()
