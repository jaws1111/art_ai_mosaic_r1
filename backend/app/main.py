"""Tessera FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.routers.export_router import router as export_router
from app.routers.mosaic_router import router as mosaic_router, ws_router
from app.services.job_store import JobStore
from app.services.mosaic_service import MosaicService
from app.services.quality_service import QualityService

settings = get_settings()
job_store = JobStore(settings.data_dir / "state" / "jobs.sqlite")
quality_service = QualityService(settings, job_store)
mosaic_service = MosaicService(settings, job_store, quality_service)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_dirs()
    await job_store.init()
    yield


app = FastAPI(title="Tessera Mosaic Engine", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5522", "http://127.0.0.1:5522"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(mosaic_router)
app.include_router(export_router)
app.include_router(ws_router)

if settings.data_dir.exists():
    app.mount("/data", StaticFiles(directory=str(settings.data_dir)), name="data")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "tessera"}
