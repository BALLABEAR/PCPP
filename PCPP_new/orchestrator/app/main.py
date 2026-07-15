from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.db import Base, engine
from app.core.health import router as health_router
from app.model_catalog.router import router as model_catalog_router
from app.model_onboarding.router import router as model_onboarding_router
from app.pipeline_builder.router import router as pipeline_builder_router
from app.pipeline_run.router import router as pipeline_run_router
from app.training.router import router as training_router

app = FastAPI(title="PCPP_new Orchestrator", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3010", "http://127.0.0.1:3010"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(model_onboarding_router)
app.include_router(model_catalog_router)
app.include_router(pipeline_run_router)
app.include_router(pipeline_builder_router)
app.include_router(training_router)


# Создает таблицы БД при запуске приложения
@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
