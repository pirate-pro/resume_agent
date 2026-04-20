import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

os.environ.setdefault("POSTGRES_DSN", "postgresql+psycopg://postgres:postgres@localhost:54329/resume_agent")
os.environ.setdefault("AUTO_SEED_JOBS", "false")
os.environ.setdefault("APP_DEBUG", "false")
os.environ.setdefault("LLM_ENABLED", "false")
os.environ.setdefault("LLM_BASE_URL", "")
os.environ.setdefault("LLM_API_KEY", "")
os.environ.setdefault("LLM_MODEL_NAME", "")

from app.core.db.base import Base
from app.core.db.session import SessionLocal
from app.main import create_app
from app.application.task_worker import DatabaseTaskWorker
from app.tools.seed_jobs import seed_default_jobs


def _reset_schema() -> None:
    engine = create_engine(os.environ["POSTGRES_DSN"])
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE;")
        connection.exec_driver_sql("CREATE SCHEMA public;")
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    engine.dispose()


def _truncate_all_tables() -> None:
    with SessionLocal() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))
        session.commit()
        seed_default_jobs(session)
        session.commit()


@pytest.fixture(scope="session", autouse=True)
def setup_database() -> None:
    _reset_schema()
    _truncate_all_tables()


@pytest.fixture(autouse=True)
def clean_database() -> None:
    _truncate_all_tables()


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def task_worker() -> DatabaseTaskWorker:
    return DatabaseTaskWorker(session_factory=SessionLocal, worker_id="test-worker")


@pytest.fixture
def sample_resume_text() -> str:
    return """王小明
Email: wangxiaoming@example.com
Phone: +86 13800000000
Summary:
5年后端开发经验，负责简历解析与任务编排系统。
Skills:
Python, FastAPI, SQLAlchemy, PostgreSQL, Docker, Redis
Experience:
2021-01 to 2024-12 | Blue River Tech | Senior Backend Engineer | Built job matching APIs with FastAPI and PostgreSQL
2019-01 to 2020-12 | Atlas AI | Backend Engineer | Owned workflow services with Python and Redis
Projects:
Resume Match Platform | Lead Engineer | Python, FastAPI, PostgreSQL | Improved matching precision by 20%
Education:
本科
Target:
城市: Shanghai
"""


@pytest.fixture
def sample_resume_docx(tmp_path: Path, sample_resume_text: str) -> Path:
    from docx import Document

    path = tmp_path / "resume.docx"
    document = Document()
    for line in sample_resume_text.splitlines():
        document.add_paragraph(line)
    document.save(path)
    return path


@pytest.fixture
def sample_resume_pdf(tmp_path: Path, sample_resume_text: str) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    path = tmp_path / "resume.pdf"
    pdf = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    for line in sample_resume_text.splitlines():
        pdf.drawString(50, y, line)
        y -= 20
    pdf.save()
    return path
