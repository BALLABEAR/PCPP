import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from orchestrator.api.files import router as files_router
from orchestrator.api.onboarding import router as onboarding_router
from orchestrator.api.pipelines import router as pipelines_router
from orchestrator.api.registry import router as registry_router
from orchestrator.api.tasks import router as tasks_router
from orchestrator.api.training import router as training_router
from orchestrator.models import Base, SessionLocal, engine
from orchestrator.registry.scanner import scan_model_cards

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("orchestrator")

app = FastAPI(title="PCPP Orchestrator", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(files_router)
app.include_router(tasks_router)
app.include_router(registry_router)
app.include_router(pipelines_router)
app.include_router(onboarding_router)
app.include_router(training_router)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    root_path = Path(os.getenv("WORKSPACE_ROOT", "/app"))
    db = SessionLocal()
    try:
        found = scan_model_cards(db, root_path)
    finally:
        db.close()
    logger.info("Startup complete. model_cards found: %s", found)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
