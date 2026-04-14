from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DATA_KIND_FORMATS: dict[str, list[str]] = {
    "point_cloud": [".xyz", ".ply", ".pcd", ".pts", ".txt", ".npy", ".las", ".laz"],
    "mesh": [".obj", ".stl", ".off", ".ply"],
}


class ValidateModelRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_id: str
    task_type: str
    repo_path: str
    weights_path: str
    config_path: str
    input_data_kind: Literal["point_cloud", "mesh"] = "point_cloud"
    output_data_kind: Literal["point_cloud", "mesh"] = "point_cloud"


class ValidateModelResponse(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]
    normalized: dict[str, Any]


class ScaffoldModelRequest(ValidateModelRequest):
    model_config = ConfigDict(protected_namespaces=())
    description: str = "Generated adapter scaffold. Replace template logic with real inference."
    overwrite: bool = False
    entry_command: str = ""
    extra_pip_packages: list[str] = Field(default_factory=list)
    pip_requirements_files: list[str] = Field(default_factory=list)
    pip_extra_args: list[str] = Field(default_factory=list)
    system_packages: list[str] = Field(default_factory=list)
    base_image: str = ""
    extra_build_steps: list[str] = Field(default_factory=list)
    env_overrides: dict[str, str] = Field(default_factory=dict)


class ActionRunRequest(BaseModel):
    command: list[str]
    cwd: str | None = None


class BuildRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    task_type: str
    model_id: str
    image_tag: str | None = None
    no_cache: bool = False


class CleanupRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    task_type: str
    model_id: str


class SmokeRunRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    task_type: str
    model_id: str
    input_path: str | None = None
    input_data_kind: Literal["point_cloud", "mesh"] = "point_cloud"
    output_dir: str = "./examples/model_outputs"
    image_tag: str | None = None
    use_gpu: bool = True
    model_args: list[str] = Field(default_factory=list)
    smoke_args: str = ""


class RegistryCheckRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_id: str


class PreflightScanRequest(ValidateModelRequest):
    pass


class CleanupBackupsRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    task_type: str | None = None
    model_id: str | None = None
    apply: bool = False
    older_than_hours: int = 0


class RunStatusResponse(BaseModel):
    run_id: str
    kind: Literal["build", "smoke", "command"]
    status: Literal["pending", "running", "completed", "failed"]
    command: list[str]
    cwd: str
    logs: str
    started_at_utc: str
    finished_at_utc: str | None
    exit_code: int | None
    error_hint: dict[str, str] | None
