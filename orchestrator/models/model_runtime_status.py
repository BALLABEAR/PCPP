from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from orchestrator.models import Base


class ModelRuntimeStatus(Base):
    __tablename__ = "model_runtime_status"

    model_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("model_cards.id", ondelete="CASCADE"),
        primary_key=True,
    )
    build_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    smoke_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_build_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_smoke_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_image_tag: Mapped[str | None] = mapped_column(String(256), nullable=True)
    manifest_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
