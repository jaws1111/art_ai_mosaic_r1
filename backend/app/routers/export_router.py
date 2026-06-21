"""Job export and download endpoints."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse

router = APIRouter(prefix="/api/mosaic", tags=["export"])


@router.get("/jobs/{job_id}/export")
async def export_job_zip(job_id: str) -> StreamingResponse:
    """Download all final artifacts as a zip."""
    from app.main import job_store

    job = await job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    outputs = json.loads(job["outputs_json"] or "{}")
    run_root = Path(job["run_path"]).resolve()
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "job_id": job_id,
                    "prompt": job["prompt"],
                    "outputs": {k: v for k, v in outputs.items() if not str(k).startswith("_")},
                },
                indent=2,
            ),
        )
        for key in (
            "blueprint",
            "mosaic_hard_paste",
            "mosaic_feather_blend",
            "master_bigtiff",
        ):
            rel = outputs.get(key)
            if not rel or not isinstance(rel, str):
                continue
            file_path = (run_root / rel).resolve()
            if file_path.is_file() and str(file_path).startswith(str(run_root)):
                zf.write(file_path, arcname=f"{key}{file_path.suffix}")

    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="tessera_{job_id}.zip"'},
    )


@router.get("/jobs/{job_id}/download/{artifact}")
async def download_artifact(job_id: str, artifact: str) -> Response:
    """Download a single artifact: feather | hard | blueprint | bigtiff."""
    from app.main import job_store

    key_map = {
        "feather": "mosaic_feather_blend",
        "hard": "mosaic_hard_paste",
        "blueprint": "blueprint",
        "bigtiff": "master_bigtiff",
    }
    output_key = key_map.get(artifact)
    if not output_key:
        raise HTTPException(status_code=400, detail=f"Unknown artifact: {artifact}")

    job = await job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    outputs = json.loads(job["outputs_json"] or "{}")
    rel = outputs.get(output_key)
    if not rel or not isinstance(rel, str):
        raise HTTPException(status_code=404, detail="Artifact not ready")

    run_root = Path(job["run_path"]).resolve()
    file_path = (run_root / rel).resolve()
    if not file_path.is_file() or not str(file_path).startswith(str(run_root)):
        raise HTTPException(status_code=404, detail="File not found")

    data = file_path.read_bytes()
    media = "application/octet-stream"
    if file_path.suffix.lower() == ".png":
        media = "image/png"
    elif file_path.suffix.lower() in {".tif", ".tiff"}:
        media = "image/tiff"

    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{file_path.name}"'},
    )
