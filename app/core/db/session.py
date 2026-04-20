from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config.settings import get_settings
from app.core.db.base import Base
from app.core.db.models import entities  # noqa: F401

settings = get_settings()

engine = create_engine(
    settings.postgres_dsn,
    echo=settings.sqlalchemy_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all_if_needed() -> None:
    Base.metadata.create_all(bind=engine)
