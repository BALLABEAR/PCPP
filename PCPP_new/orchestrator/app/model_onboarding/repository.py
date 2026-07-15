from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.db_models import ModelCard, OnboardingRun
from app.model_onboarding.schemas import ModelPayload


# Ищет активную модель по model_id
def find_active_model(db: Session, model_id: str) -> ModelCard | None:
    return db.query(ModelCard).filter(ModelCard.model_id == model_id, ModelCard.is_active.is_(True)).first()


# Создает запись запуска onboarding/build
def create_run(db: Session, model_id: str) -> OnboardingRun:
    run = OnboardingRun(id=uuid.uuid4().hex, model_id=model_id)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


# Сохраняет карточку модели после успешного scaffold
def save_model_card(db: Session, payload: ModelPayload) -> ModelCard:
    card = ModelCard(
        model_id=payload.model_id,
        task_type=payload.task_type,
        repo_path=payload.repo_path,
        weights_path=payload.weights_path,
        config_path=payload.config_path,
        smoke_input_path=payload.smoke_input_path,
        entry_command=payload.entry_command,
        extra_pip_packages=payload.extra_pip_packages,
        pip_requirements_files=payload.pip_requirements_files,
        pip_extra_args=payload.pip_extra_args,
        system_packages=payload.system_packages,
        base_image=payload.base_image,
        extra_build_steps=payload.extra_build_steps,
        env_overrides=payload.env_overrides,
        smoke_args=payload.smoke_args,
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return card


# Возвращает запуск по идентификатору
def get_run(db: Session, run_id: str) -> OnboardingRun | None:
    return db.get(OnboardingRun, run_id)


# Возвращает все активные модели в порядке обновления
def list_active_models(db: Session) -> list[ModelCard]:
    return db.query(ModelCard).filter(ModelCard.is_active.is_(True)).order_by(ModelCard.created_at.desc()).all()


# Безопасно возвращает запуск или None
def get_run_or_none(db: Session, run_id: str) -> OnboardingRun | None:
    return db.get(OnboardingRun, run_id)
