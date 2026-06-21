"""Orchestrates post-job quality review with optional AI critique."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings
from app.models.mosaic import JobStatus
from app.services.job_store import JobStore
from app.services.quality_assessment import QualityMetrics, generate_comparison_artifacts
from app.services.telemetry import job_telemetry
from app.services.xai_critique import request_mosaic_critique

logger = logging.getLogger(__name__)


def _extract_scale_field(critique: str | None) -> str | None:
    if not critique:
        return None
    for line in critique.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("SCALE:"):
            return stripped.split(":", 1)[1].strip().lower()
    return None


def _metrics_to_dict(m: QualityMetrics) -> dict:
    return {
        "ssim": m.ssim,
        "edge_overlap": m.edge_overlap,
        "mse": m.mse,
        "detail_ratio": m.detail_ratio,
        "overall_score": m.overall_score,
        "passed": m.passed,
        "notes": m.notes,
    }


class QualityService:
    def __init__(self, settings: Settings, store: JobStore) -> None:
        self.settings = settings
        self.store = store
        self._running: dict[str, asyncio.Task] = {}

    async def run_quality_review(
        self,
        job_id: str,
        *,
        include_ai_critique: bool = False,
        on_progress=None,
    ) -> dict:
        job = await self.store.get_job(job_id)
        if not job:
            raise ValueError("Job not found")

        outputs = json.loads(job["outputs_json"] or "{}")
        blueprint_rel = outputs.get("blueprint")
        mosaic_rel = outputs.get("mosaic_feather_blend") or outputs.get("mosaic_hard_paste")
        if not blueprint_rel or not mosaic_rel:
            raise ValueError("Job missing blueprint or mosaic outputs")

        run_root = Path(job["run_path"]).resolve()
        blueprint_path = (run_root / str(blueprint_rel)).resolve()
        mosaic_path = (run_root / str(mosaic_rel)).resolve()
        quality_dir = run_root / "final" / "quality"

        report = {
            "status": "running",
            "stage": "metrics",
            "message": "Computing structure metrics…",
            "include_ai_critique": include_ai_critique,
        }
        await self._save_report(job_id, report, on_progress)

        def build_artifacts():
            return generate_comparison_artifacts(
                blueprint_path,
                mosaic_path,
                quality_dir,
                max_px=self.settings.quality_review_max_px,
            )

        metrics, artifacts = await asyncio.to_thread(build_artifacts)
        rel_artifacts = {
            key: str(path.relative_to(run_root)).replace("\\", "/")
            for key, path in artifacts.items()
        }

        report.update(
            {
                "status": "running",
                "stage": "artifacts",
                "message": "Comparison images ready",
                "metrics": _metrics_to_dict(metrics),
                "artifacts": rel_artifacts,
            }
        )
        await self._save_report(job_id, report, on_progress)

        ai_critique = None
        if include_ai_critique and self.settings.quality_ai_critique_enabled:
            report.update(
                {
                    "stage": "ai_critique",
                    "message": "Requesting xAI vision critique (token-limited)…",
                }
            )
            await self._save_report(job_id, report, on_progress)
            try:
                ai_critique = await request_mosaic_critique(
                    self.settings,
                    artifacts["side_by_side"],
                    artifacts.get("outline"),
                    max_output_tokens=self.settings.quality_ai_max_tokens,
                )
                job_telemetry.increment_api_calls(job_id)
            except Exception as exc:
                logger.warning("AI critique skipped for %s: %s", job_id, exc)
                ai_critique = f"(Critique unavailable: {exc})"

        ai_scale = _extract_scale_field(ai_critique) if ai_critique else None
        report.update(
            {
                "status": "complete",
                "stage": "complete",
                "message": f"Quality review complete — score {metrics.overall_score}/100",
                "metrics": _metrics_to_dict(metrics),
                "artifacts": rel_artifacts,
                "ai_critique": ai_critique,
                "ai_scale": ai_scale,
            }
        )
        await self._save_report(job_id, report, on_progress)
        return report

    async def _save_report(
        self,
        job_id: str,
        report: dict,
        on_progress,
    ) -> None:
        job = await self.store.get_job(job_id)
        if not job:
            return
        outputs = json.loads(job["outputs_json"] or "{}")
        outputs["quality_report"] = report
        await self.store.update_job_status(
            job_id,
            JobStatus(job["status"]),
            outputs=outputs,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        job_telemetry.log(
            job_id,
            "system",
            str(report.get("message", "Quality update")),
            str(report.get("stage")),
        )
        if on_progress:
            await on_progress(report)

    def start_background(
        self,
        job_id: str,
        *,
        include_ai_critique: bool,
        on_progress,
    ) -> None:
        if job_id in self._running and not self._running[job_id].done():
            return
        task = asyncio.create_task(
            self._run_safe(job_id, include_ai_critique=include_ai_critique, on_progress=on_progress)
        )
        self._running[job_id] = task
        task.add_done_callback(lambda _: self._running.pop(job_id, None))

    async def _run_safe(self, job_id: str, *, include_ai_critique: bool, on_progress) -> None:
        try:
            await self.run_quality_review(job_id, include_ai_critique=include_ai_critique, on_progress=on_progress)
        except Exception as exc:
            logger.exception("Quality review failed for %s", job_id)
            job = await self.store.get_job(job_id)
            if job:
                outputs = json.loads(job["outputs_json"] or "{}")
                outputs["quality_report"] = {
                    "status": "failed",
                    "stage": "failed",
                    "message": str(exc),
                }
                await self.store.update_job_status(
                    job_id,
                    JobStatus(job["status"]),
                    outputs=outputs,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )
                if on_progress:
                    await on_progress(outputs["quality_report"])
