from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from orchestrator.models import Base


class TrainingRun(Base):
    __tablename__ = "training_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset_root: Mapped[str] = mapped_column(String(512), nullable=False)
    train_script: Mapped[str] = mapped_column(String(512), nullable=False)
    config_path: Mapped[str] = mapped_column(String(512), nullable=False)
    resolved_config_path: Mapped[str] = mapped_column(String(512), nullable=False)
    run_dir: Mapped[str] = mapped_column(String(512), nullable=False)
    logs_path: Mapped[str] = mapped_column(String(512), nullable=False)
    metrics_path: Mapped[str] = mapped_column(String(512), nullable=False)
    command_json: Mapped[str] = mapped_column(Text, nullable=False)
    best_checkpoint_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
