from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from orchestrator.api.dependencies import get_db
from orchestrator.models.pipeline import Pipeline
from flows.flow_definitions import get_pipeline_templates

router = APIRouter(prefix="/pipelines", tags=["pipelines"])

class PipelineResponse(BaseModel):
    id: str
    name: str
    config_yaml: str | None


class CreatePipelineRequest(BaseModel):
    name: str
    config_yaml: str | None = None


@router.get("/templates")
def list_pipeline_templates() -> list[dict]:
    return get_pipeline_templates()


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

