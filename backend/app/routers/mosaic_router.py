"""Mosaic job API routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from app.models.mosaic import JobProgress, JobStatus, MosaicJobCreate
from app.services.plan_preview import PlanPreviewRequest, PlanPreviewResponse, preview_plan
from app.services.local_gpu import is_comfyui_available
from app.services.progress_hub import progress_hub

router = APIRouter(prefix="/api/mosaic", tags=["mosaic"])
ws_router = APIRouter(tags=["websocket"])


def get_service():
    from app.main import mosaic_service

    return mosaic_service


@router.post("/plan", response_model=PlanPreviewResponse)
async def preview_canvas_plan(request: PlanPreviewRequest) -> PlanPreviewResponse:
    """Preview generation strategy and tile count before starting a job."""
    return preview_plan(request)


@router.get("/gpu-status")
async def gpu_status() -> dict:
    """ComfyUI / local GPU availability (Phase 1.4)."""
    from app.core.config import get_settings

    settings = get_settings()
    available = await is_comfyui_available(settings)
    return {
        "comfyui_enabled": settings.comfyui_enabled,
        "comfyui_url": settings.comfyui_url,
        "available": available,
        "upscale_model": settings.comfyui_upscale_model,
    }


from pydantic import BaseModel, Field


class JobRenameRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


class QualityRunRequest(BaseModel):
    include_ai_critique: bool = False


@router.patch("/jobs/{job_id}/name", response_model=JobProgress)
async def rename_job(job_id: str, request: JobRenameRequest) -> JobProgress:
    progress = await get_service().rename_job(job_id, request.display_name)
    if not progress:
        raise HTTPException(status_code=404, detail="Job not found")
    return progress


@router.post("/jobs/{job_id}/quality")
async def run_quality_review(job_id: str, request: QualityRunRequest) -> dict:
    job = await get_service().get_progress(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.COMPLETE:
        raise HTTPException(status_code=400, detail="Quality review requires a completed job")
    await get_service().trigger_quality_review(
        job_id,
        include_ai_critique=request.include_ai_critique,
    )
    return {"status": "started", "job_id": job_id}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict:
    """Cancel a running job gracefully."""
    svc = get_service()
    ok = await svc.cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found or not running")
    return {"status": "cancelling", "job_id": job_id}


@router.post("/jobs", response_model=JobProgress)
async def create_job(request: MosaicJobCreate) -> JobProgress:
    return await get_service().create_job(request)


@router.get("/jobs", response_model=list[dict])
async def list_jobs() -> list[dict]:
    from app.main import job_store

    return await job_store.list_jobs()


@router.get("/jobs/{job_id}", response_model=JobProgress)
async def get_job(job_id: str) -> JobProgress:
    progress = await get_service().get_progress(job_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Job not found")
    return progress


@router.get("/jobs/{job_id}/files/{file_path:path}")
async def get_job_file(job_id: str, file_path: str) -> FileResponse:
    """Serve run artifacts (blueprint, tiles, finals) — fixes frontend 404s."""
    from app.main import job_store

    job = await job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    run_root = Path(job["run_path"]).resolve()
    target = (run_root / file_path).resolve()

    if not str(target).startswith(str(run_root)):
        raise HTTPException(status_code=403, detail="Invalid path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    media = "image/png"
    suffix = target.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        media = "image/jpeg"
    elif suffix in {".tif", ".tiff"}:
        media = "image/tiff"
    elif suffix == ".dzi":
        media = "application/xml"

    return FileResponse(target, media_type=media)


@ws_router.websocket("/ws/progress/{job_id}")
async def ws_progress(websocket: WebSocket, job_id: str) -> None:
    progress = await get_service().get_progress(job_id)
    if not progress:
        await websocket.close(code=4404)
        return

    await progress_hub.connect(job_id, websocket)
    try:
        await websocket.send_json(progress.model_dump())
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await progress_hub.disconnect(job_id, websocket)
