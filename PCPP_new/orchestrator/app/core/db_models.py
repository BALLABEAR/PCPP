from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


# Карточка зарегистрированной модели для onboarding и запуска пайплайнов
class ModelCard(Base):
    __tablename__ = "models"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    repo_path: Mapped[str] = mapped_column(Text, nullable=False)
    weights_path: Mapped[str] = mapped_column(Text, nullable=False)
    config_path: Mapped[str] = mapped_column(Text, nullable=False)
    smoke_input_path: Mapped[str] = mapped_column(Text, nullable=False)
    entry_command: Mapped[str] = mapped_column(Text, default="", nullable=False)
    extra_pip_packages: Mapped[str] = mapped_column(Text, default="", nullable=False)
    pip_requirements_files: Mapped[str] = mapped_column(Text, default="", nullable=False)
    pip_extra_args: Mapped[str] = mapped_column(Text, default="", nullable=False)
    system_packages: Mapped[str] = mapped_column(Text, default="", nullable=False)
    base_image: Mapped[str] = mapped_column(Text, default="", nullable=False)
    extra_build_steps: Mapped[str] = mapped_column(Text, default="", nullable=False)
    env_overrides: Mapped[str] = mapped_column(Text, default="", nullable=False)
    smoke_args: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# Запись состояния и логов одного onboarding/build запуска
class OnboardingRun(Base):
    __tablename__ = "onboarding_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="pending", nullable=False)
    stage_validate: Mapped[str] = mapped_column(Text, default="pending", nullable=False)
    stage_scaffold: Mapped[str] = mapped_column(Text, default="pending", nullable=False)
    stage_build: Mapped[str] = mapped_column(Text, default="pending", nullable=False)
    stage_smoke: Mapped[str] = mapped_column(Text, default="pending", nullable=False)
    stage_registry: Mapped[str] = mapped_column(Text, default="pending", nullable=False)
    logs: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
