from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.models import Base


class ModelCard(Base):
    __tablename__ = "model_cards"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    source_path: Mapped[str] = mapped_column(String(512), nullable=False)

