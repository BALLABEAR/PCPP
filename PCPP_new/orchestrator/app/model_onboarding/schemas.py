from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# DTO входных данных для validate/scaffold onboarding
class ModelPayload(BaseModel):
    task_type: str
    model_id: str
    repo_path: str
    weights_path: str
    config_path: str
    smoke_input_path: str = Field(alias="smoke_input_path")
    entry_command: str = ""
    extra_pip_packages: str = ""
    pip_requirements_files: str = ""
    pip_extra_args: str = ""
    system_packages: str = ""
    base_image: str = ""
    extra_build_steps: str = ""
    env_overrides: str = ""
    smoke_args: str = ""

    @field_validator("model_id")
    @classmethod
    def normalize_model_id(cls, value: str) -> str:
        return str(value or "").strip().lower()


# DTO результата валидации модели перед scaffold
class ValidateResponse(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]


# DTO статусов этапов onboarding-пайплайна
class StageState(BaseModel):
    validate: str
    scaffold: str
    build: str
    smoke: str
    registry: str


# DTO состояния и логов одного запуска onboarding/build
class RunResponse(BaseModel):
    run_id: str
    model_id: str
    status: str
    stages: StageState
    logs: str
    error_message: str | None
    created_at: datetime | None
    updated_at: datetime | None
