from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from orchestrator.api.dependencies import get_db
from orchestrator.models.pipeline import Pipeline

router = APIRouter(prefix="/pipelines", tags=["pipelines"])

PIPELINE_TEMPLATES: list[dict] = [
    {
        "id": "stage2_test",
        "name": "Stage 2 Test Flow",
        "flow_id": "stage2_test_flow",
        "description": "MinIO -> fake worker -> MinIO result",
        "flow_params": {},
    },
    {
        "id": "stage4_real_two_model",
        "name": "Stage 4 Real (Completion -> Meshing)",
        "flow_id": "stage4_real_two_model_flow",
        "description": "SnowflakeNet completion + ShapeAsPoints meshing",
        "flow_params": {
            "completion_mode": "model",
            "completion_weights_path": "external_models/SnowflakeNet/pretrained_completion/ckpt-best-c3d-cd_l2.pth",
            "completion_config_path": "external_models/SnowflakeNet/completion/configs/c3d_cd2.yaml",
            "completion_device": "cuda",
            "meshing_repo_path": "external_models/ShapeAsPoints",
            "meshing_config_path": "configs/optim_based/teaser.yaml",
            "meshing_total_epochs": 200,
            "meshing_grid_res": 128,
            "meshing_no_cuda": False,
        },
    },
    {
        "id": "stage4_snowflake_only",
        "name": "Stage 4 Snowflake Only",
        "flow_id": "stage4_snowflake_only_flow",
        "description": "Single-step completion flow with SnowflakeNet only",
        "flow_params": {
            "completion_mode": "model",
            "completion_weights_path": "external_models/SnowflakeNet/pretrained_completion/ckpt-best-c3d-cd_l2.pth",
            "completion_config_path": "external_models/SnowflakeNet/completion/configs/c3d_cd2.yaml",
            "completion_device": "cuda",
        },
    },
    {
        "id": "stage4_shape_as_points_only",
        "name": "Stage 4 ShapeAsPoints Only",
        "flow_id": "stage4_shape_as_points_only_flow",
        "description": "Single-step meshing flow with ShapeAsPoints only",
        "flow_params": {
            "meshing_repo_path": "external_models/ShapeAsPoints",
            "meshing_config_path": "configs/optim_based/teaser.yaml",
            "meshing_total_epochs": 20,
            "meshing_grid_res": 64,
            "meshing_no_cuda": False,
        },
    },
]


class PipelineResponse(BaseModel):
    id: str
    name: str
    config_yaml: str | None


class CreatePipelineRequest(BaseModel):
    name: str
    config_yaml: str | None = None


@router.get("/templates")
def list_pipeline_templates() -> list[dict]:
    return PIPELINE_TEMPLATES


@router.get("", response_model=list[PipelineResponse])
def list_pipelines(db: Session = Depends(get_db)) -> list[PipelineResponse]:
    pipelines = db.query(Pipeline).order_by(Pipeline.created_at.desc()).all()
    return [PipelineResponse.model_validate(pipeline, from_attributes=True) for pipeline in pipelines]


@router.post("", response_model=PipelineResponse)
def create_pipeline(payload: CreatePipelineRequest, db: Session = Depends(get_db)) -> PipelineResponse:
    existing = db.query(Pipeline).filter(Pipeline.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Pipeline with this name already exists")

    pipeline = Pipeline(name=payload.name, config_yaml=payload.config_yaml)
    db.add(pipeline)
    db.commit()
    db.refresh(pipeline)
    return PipelineResponse.model_validate(pipeline, from_attributes=True)


@router.get("/{pipeline_id}", response_model=PipelineResponse)
def get_pipeline(pipeline_id: str, db: Session = Depends(get_db)) -> PipelineResponse:
    pipeline = db.get(Pipeline, pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return PipelineResponse.model_validate(pipeline, from_attributes=True)


@router.delete("/{pipeline_id}")
def delete_pipeline(pipeline_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    pipeline = db.get(Pipeline, pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    db.delete(pipeline)
    db.commit()
    return {"status": "deleted", "id": pipeline_id}

