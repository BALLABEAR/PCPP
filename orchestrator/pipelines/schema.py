from typing import Any

from pydantic import BaseModel, Field


class DraftStepRequest(BaseModel):
    model_id: str
    params: dict[str, Any] = Field(default_factory=dict)


class ValidateDraftRequest(BaseModel):
    name: str
    steps: list[DraftStepRequest]


class NormalizedStepResponse(BaseModel):
    name: str
    model_id: str
    task_type: str
    input_formats: list[str]
    output_formats: list[str]
    worker_module: str
    worker_class: str
    execution_mode: str
    dockerfile_path: str
    image_tag: str
    cli_args: dict[str, Any] = Field(default_factory=dict)


class ValidateDraftResponse(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    normalized_steps: list[NormalizedStepResponse] = Field(default_factory=list)


class CreateDraftRequest(ValidateDraftRequest):
    pass


class CreatePipelineRequest(BaseModel):
    name: str
    config_yaml: str | None = None


class PipelineResponse(BaseModel):
    id: str
    name: str
    config_yaml: str | None


class PipelineTemplateResponse(BaseModel):
    id: str
    name: str
    flow_id: str
    description: str
    flow_params: dict[str, Any] = Field(default_factory=dict)
    source: str
    pipeline_id: str | None = None
