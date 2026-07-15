from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import get_database_url

engine = create_engine(get_database_url(), future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


# Выдает SQLAlchemy-сессию и гарантирует ее закрытие после запроса
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
