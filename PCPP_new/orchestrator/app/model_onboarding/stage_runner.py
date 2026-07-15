from __future__ import annotations

from app.core.db_models import OnboardingRun
from app.model_onboarding.schemas import StageState


# Добавляет строку в агрегированный лог запуска
def append_log(run: OnboardingRun, text: str) -> None:
    run.logs = f"{run.logs}{text.rstrip()}\n"


# Устанавливает статус указанного этапа запуска
def set_stage(run: OnboardingRun, stage_name: str, value: str) -> None:
    setattr(run, f"stage_{stage_name}", value)


# Преобразует ORM-сущность запуска в DTO стадий
def to_stage_state(run: OnboardingRun) -> StageState:
    return StageState(
        validate=run.stage_validate,
        scaffold=run.stage_scaffold,
        build=run.stage_build,
        smoke=run.stage_smoke,
        registry=run.stage_registry,
    )
