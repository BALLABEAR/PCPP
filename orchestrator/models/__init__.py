import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://pcpp_user:pcpp_password@postgres:5432/pcpp",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

from orchestrator.models.model_card import ModelCard  # noqa: E402
from orchestrator.models.model_runtime_status import ModelRuntimeStatus  # noqa: E402
from orchestrator.models.pipeline import Pipeline  # noqa: E402
from orchestrator.models.task import Task  # noqa: E402

