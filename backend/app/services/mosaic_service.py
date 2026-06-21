"""Wavefront mosaic job orchestration with live telemetry."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings, project_root
from app.core.grid_math import (
    GenerationMode,
    GridPlan,
    GridPlanRequest,
    build_grid_plan,
    closest_xai_aspect_ratio,
    closing_pass_tiles,
    spatial_context_for_tile,
    tile_key,
    wavefront_order,
    wrap_flags_for_canvas,
)
from app.core.storage import RunPaths
from app.models.mosaic import JobProgress, JobStatus, MosaicJobCreate, TileState, TileStatus
from app.models.regions import PromptRegion
from app.services.compositor import stitch_all_tiles_memmap
from app.services.compositor_simple import stitch_all_tiles
from app.services.dzi_builder import build_dzi
from app.services.image_utils import (
    crop_blueprint_for_tile,
    ensure_rgb_image,
    normalize_blueprint_for_plan,
    save_overlap_reference,
    save_rgb_image,
)
from app.services.job_store import JobStore
from app.services.local_enhance import resize_to_canvas
from app.services.local_gpu import LocalRTX4080Service, is_comfyui_available
from app.services.local_upscale_gpu import cuda_available, upscale_tile_gpu
from app.services.local_refinery import refine_tile_sync
from app.services.overlap_qa import score_tile_seams
from app.services.progress_hub import progress_hub
from app.services.region_prompts import build_blueprint_prompt, build_regional_tile_prompt
from app.services.seam_repair import repair_tile_seams
from app.services.telemetry import job_telemetry
from app.services.xai_adapter import XAIImageEngine

logger = logging.getLogger(__name__)


def build_wavefront_sequence(rows: int, cols: int) -> list[tuple[int, int, int]]:
    sequence: list[tuple[int, int, int]] = []
    seq = 1
    for wave in wavefront_order(rows, cols):
        for row, col in wave:
            sequence.append((seq, row, col))
            seq += 1
    return sequence


def build_tile_prompt(
    style_anchor: str,
    master_prompt: str,
    row: int,
    col: int,
    rows: int,
    cols: int,
    regions: list[PromptRegion] | None = None,
) -> str:
    spatial = spatial_context_for_tile(row, col, rows, cols)
    if regions:
        return build_regional_tile_prompt(
            style_anchor, master_prompt, regions, row, col, rows, cols, spatial
        )
    anchor = (style_anchor.rstrip(", ") + ", ") if style_anchor else ""
    return (
        f"{anchor}ultra-high detail, 2K resolution render. "
        f"Scene: {master_prompt}. "
        f"This is tile row {row + 1}/{rows}, col {col + 1}/{cols} ({spatial}). "
        "<IMAGE_0> defines the COMPOSITION and SUBJECT PLACEMENT for this region — use it as a "
        "layout guide. Now render this region at FULL 2K quality: add rich surface textures, "
        "fine structural details, volumetric lighting, atmospheric depth, and surface imperfections "
        "that the rough blueprint sketch does not show. Every surface should be detailed. "
        "Do NOT zoom out to show the full scene. Keep subjects at the same scale as IMAGE_0. "
        "<IMAGE_1> = left neighbour edge (match colour/lighting at left boundary seamlessly). "
        "<IMAGE_2> = top neighbour edge (match colour/lighting at top boundary seamlessly)."
    )


class MosaicService:
    def __init__(self, settings: Settings, store: JobStore, quality_service=None) -> None:
        self.settings = settings
        self.store = store
        self.quality = quality_service
        self._running: dict[str, asyncio.Task] = {}
        self._started: dict[str, datetime] = {}
        self._job_context: dict[str, tuple[MosaicJobCreate, GridPlan]] = {}

    async def create_job(self, request: MosaicJobCreate) -> JobProgress:
        job_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc)
        wrap_h, wrap_v = wrap_flags_for_canvas(request.canvas.mode, request.canvas.wraparound)
        plan = build_grid_plan(
            GridPlanRequest(
                width_px=request.canvas.width_px,
                height_px=request.canvas.height_px,
                base_tile_px=self.settings.base_tile_px,
                upscale_factor=request.upscale_factor,
                overlap_fraction=request.overlap_fraction,
                wrap_horizontal=wrap_h,
                wrap_vertical=wrap_v,
            )
        )
        paths = RunPaths.create(self.settings.runs_dir, f"job_{job_id}")
        paths.ensure_all()

        tiles = [
            TileState(row=row, col=col, seq=seq, status=TileStatus.QUEUED)
            for seq, row, col in build_wavefront_sequence(plan.rows, plan.cols)
        ]
        regions_json = json.dumps([r.model_dump() for r in request.regions])
        display_name = (request.display_name or request.prompt[:60]).strip()

        await self.store.create_job(
            job_id=job_id,
            prompt=request.prompt,
            style_anchor=request.style_anchor,
            canvas_json=request.canvas.model_dump_json(),
            grid_json=plan.model_dump_json(),
            run_path=str(paths.root),
            created_at=now.isoformat(),
            regions_json=regions_json,
            display_name=display_name,
            run_quality_check=request.run_quality_check,
            include_ai_critique=request.include_ai_critique,
        )
        await self.store.upsert_tiles(job_id, tiles)

        job_telemetry.init_job(job_id)
        self._started[job_id] = now
        job_telemetry.log(
            job_id,
            "system",
            "Strategy selected",
            plan.strategy_message,
            ts=0.0,
        )
        if request.regions:
            job_telemetry.log(
                job_id,
                "system",
                "Regional prompts",
                f"{len(request.regions)} zone(s) on canvas",
                ts=0.0,
            )
        if plan.wrap_horizontal or plan.wrap_vertical:
            wraps = []
            if plan.wrap_horizontal:
                wraps.append("horizontal")
            if plan.wrap_vertical:
                wraps.append("vertical")
            job_telemetry.log(
                job_id,
                "system",
                "Panorama wraparound",
                f"Closing pass enabled ({', '.join(wraps)})",
                ts=0.0,
            )

        progress = await self._build_progress(
            job_id=job_id,
            status=JobStatus.PENDING,
            prompt=request.prompt,
            plan=plan,
            stage="queued",
            message="Job queued — preparing mosaic pipeline",
            tiles=tiles,
        )
        await self._emit(progress)

        task = asyncio.create_task(self._run_job(job_id, request, plan, paths))
        self._running[job_id] = task
        task.add_done_callback(lambda _: self._running.pop(job_id, None))
        return progress

    async def get_progress(self, job_id: str) -> JobProgress | None:
        job = await self.store.get_job(job_id)
        if not job:
            return None
        plan = GridPlan.model_validate_json(job["grid_json"])
        tiles = await self.store.get_tiles(job_id)
        outputs = json.loads(job["outputs_json"] or "{}")
        return await self._build_progress(
            job_id=job_id,
            status=JobStatus(job["status"]),
            prompt=job["prompt"],
            plan=plan,
            stage=str(outputs.get("_stage", job["status"])),
            message=str(outputs.get("_message", job["status"])),
            tiles=tiles,
            outputs=outputs,
            error=job["error"],
            display_name=job.get("display_name") or "",
        )

    async def _build_progress(
        self,
        job_id: str,
        status: JobStatus,
        prompt: str,
        plan: GridPlan,
        stage: str,
        message: str,
        tiles: list[TileState],
        outputs: dict | None = None,
        error: str | None = None,
        display_name: str = "",
    ) -> JobProgress:
        started = self._started.get(job_id, datetime.now(timezone.utc))
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        complete = sum(
            1
            for t in tiles
            if t.status in (TileStatus.COMPOSITED, TileStatus.CLOUD_DONE)
        )
        clean_outputs = {k: v for k, v in (outputs or {}).items() if not str(k).startswith("_")}
        return JobProgress(
            job_id=job_id,
            display_name=display_name,
            status=status,
            prompt=prompt,
            tiles_total=plan.tile_count,
            tiles_complete=complete,
            grid_rows=plan.rows,
            grid_cols=plan.cols,
            generation_mode=plan.generation_mode.value,
            strategy_message=plan.strategy_message,
            stage=stage,
            message=message,
            elapsed_s=elapsed,
            est_cost_usd=round(0.026 * max(1, job_telemetry.get_api_calls(job_id)), 2),
            api_calls=job_telemetry.get_api_calls(job_id),
            tiles=tiles,
            outputs=clean_outputs,
            activity=job_telemetry.get_events(job_id),
            workers=job_telemetry.get_workers(job_id),
            error=error,
        )

    async def _emit(self, progress: JobProgress) -> None:
        await progress_hub.broadcast(progress.job_id, progress.model_dump())

    async def _pulse_progress(self, job_id: str) -> None:
        """Push live worker flags to WebSocket without rewriting job status."""
        ctx = self._job_context.get(job_id)
        if not ctx:
            return
        request, plan = ctx
        job = await self.store.get_job(job_id)
        if not job:
            return
        tiles = await self.store.get_tiles(job_id)
        outputs = json.loads(job["outputs_json"] or "{}")
        progress = await self._build_progress(
            job_id=job_id,
            status=JobStatus(job["status"]),
            prompt=request.prompt,
            plan=plan,
            stage=str(outputs.get("_stage", job["status"])),
            message=str(outputs.get("_message", job["status"])),
            tiles=tiles,
            outputs=outputs,
        )
        await self._emit(progress)

    async def _set_workers(self, job_id: str, *, pulse: bool = True, **kwargs: object) -> None:
        job_telemetry.set_workers(job_id, **kwargs)
        if pulse:
            await self._pulse_progress(job_id)

    async def _log(
        self,
        job_id: str,
        category: str,
        message: str,
        detail: str | None = None,
    ) -> None:
        started = self._started.get(job_id, datetime.now(timezone.utc))
        ts = (datetime.now(timezone.utc) - started).total_seconds()
        job_telemetry.log(job_id, category, message, detail, ts=ts)
        if category in ("cpu", "gpu", "network"):
            await self._pulse_progress(job_id)

    async def _refresh(
        self,
        job_id: str,
        request: MosaicJobCreate,
        plan: GridPlan,
        status: JobStatus,
        stage: str,
        message: str,
        tiles: list[TileState] | None = None,
        outputs: dict | None = None,
    ) -> None:
        if tiles is None:
            tiles = await self.store.get_tiles(job_id)
        merged_outputs: dict = {}
        job = await self.store.get_job(job_id)
        if job:
            merged_outputs = json.loads(job["outputs_json"] or "{}")
        if outputs:
            merged_outputs.update(outputs)
        merged_outputs["_message"] = message
        merged_outputs["_stage"] = stage
        await self.store.update_job_status(
            job_id,
            status,
            outputs=merged_outputs,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        progress = await self._build_progress(
            job_id=job_id,
            status=status,
            prompt=request.prompt,
            plan=plan,
            stage=stage,
            message=message,
            tiles=tiles,
            outputs=merged_outputs,
        )
        await self._emit(progress)

    async def _attach_dzi(
        self,
        job_id: str,
        paths: RunPaths,
        source_path: Path,
        outputs: dict,
    ) -> dict:
        """Build OpenSeadragon DZI pyramid from final PNG (Phase 1.6)."""
        try:
            await self._log(job_id, "cpu", "Building deep-zoom pyramid", str(source_path.name))

            def build() -> Path:
                job_telemetry.set_workers(job_id, cpu_active=True, cpu_label="DZI pyramid")
                paths.ensure_dzi_dir()
                dzi = build_dzi(source_path, paths.dzi_dir())
                job_telemetry.set_workers(job_id, cpu_active=False, cpu_label="CPU idle")
                return dzi

            dzi_path = await asyncio.to_thread(build)
            outputs["dzi"] = paths.relative(dzi_path, paths.root)
            await self._log(job_id, "system", "Deep zoom ready", outputs["dzi"])
        except Exception as exc:
            logger.warning("DZI build skipped for job %s: %s", job_id, exc)
        return outputs

    async def _refine_cloud_tile(
        self,
        job_id: str,
        plan: GridPlan,
        tile_path: Path,
        processed_path: Path,
        row: int,
        col: int,
        left_processed: Path | None,
        top_processed: Path | None,
    ) -> Path:
        """Stage 3: upscale (GPU/CPU) + seam harmonization."""
        comfyui = LocalRTX4080Service(self.settings)
        upscale_source = tile_path
        needs_upscale = plan.upscale_factor > 1 or plan.tile_effective > 2048

        if needs_upscale:
            gpu_upscaled = processed_path.with_suffix(".gpu.png")
            comfyui_ok = await comfyui.is_available()

            if comfyui_ok:
                await self._set_workers(job_id, gpu_active=True, gpu_label=f"Real-ESRGAN r{row}c{col}")
                if await comfyui.upscale_tile(tile_path, gpu_upscaled, plan.tile_effective):
                    upscale_source = gpu_upscaled
                    await self._log(job_id, "gpu", f"ComfyUI upscale r{row}c{col}", "Real-ESRGAN ✓")
                else:
                    await self._log(job_id, "gpu", f"ComfyUI upscale failed r{row}c{col}", "PyTorch fallback")
                    comfyui_ok = False
                await self._set_workers(job_id, gpu_active=False, gpu_label="GPU idle")

            if not comfyui_ok:
                use_cuda = cuda_available()
                gpu_label = f"CUDA bicubic r{row}c{col}" if use_cuda else f"CPU Lanczos r{row}c{col}"
                await self._set_workers(
                    job_id,
                    gpu_active=use_cuda,
                    gpu_label=gpu_label,
                    cpu_active=not use_cuda,
                    cpu_label=gpu_label,
                )
                await self._log(
                    job_id, "gpu" if use_cuda else "cpu",
                    f"{'CUDA' if use_cuda else 'CPU'} upscale r{row}c{col}",
                    f"{2048}→{plan.tile_effective}px bicubic+sharpen",
                )

                def do_gpu_upscale() -> None:
                    upscale_tile_gpu(tile_path, gpu_upscaled, plan.tile_effective, sharpen=True)

                await asyncio.to_thread(do_gpu_upscale)
                upscale_source = gpu_upscaled
                await self._set_workers(
                    job_id,
                    gpu_active=False, gpu_label="GPU idle",
                    cpu_active=False, cpu_label="CPU idle",
                )

        await self._set_workers(job_id, cpu_active=True, cpu_label=f"Seam repair r{row}c{col}")

        def cpu_refine() -> Path:
            return refine_tile_sync(
                upscale_source,
                processed_path,
                plan,
                left_neighbor_path=left_processed,
                top_neighbor_path=top_processed,
                settings=self.settings,
            )

        result = await asyncio.to_thread(cpu_refine)
        await self._set_workers(job_id, cpu_active=False, cpu_label="CPU idle")
        if upscale_source != tile_path and upscale_source.exists():
            upscale_source.unlink(missing_ok=True)
        return result

    async def _closing_pass_wrap(
        self,
        job_id: str,
        request: MosaicJobCreate,
        plan: GridPlan,
        processed_paths: dict[str, Path],
        tile_paths: dict[str, Path],
    ) -> None:
        """Phase 2b: re-harmonize wrap edge tiles after the full grid exists."""
        coords = closing_pass_tiles(
            plan.rows,
            plan.cols,
            wrap_horizontal=plan.wrap_horizontal,
            wrap_vertical=plan.wrap_vertical,
        )
        if not coords:
            return

        await self._log(
            job_id,
            "system",
            "Wraparound closing pass",
            f"Seam repair on {len(coords)} edge tile(s)",
        )
        await self._refresh(
            job_id,
            request,
            plan,
            JobStatus.TILING,
            "closing_pass",
            f"Closing panorama loop — {len(coords)} tile(s)",
        )

        for row, col in coords:
            key = tile_key(row, col)
            processed = processed_paths.get(key)
            if not processed or not processed.is_file():
                continue

            left_p: Path | None = None
            top_p: Path | None = None
            if col == 0 and plan.wrap_horizontal and plan.cols > 1:
                left_p = processed_paths.get(tile_key(row, plan.cols - 1))
            elif col > 0:
                left_p = processed_paths.get(tile_key(row, col - 1))
            if row == 0 and plan.wrap_vertical and plan.rows > 1:
                top_p = processed_paths.get(tile_key(plan.rows - 1, col))
            elif row > 0:
                top_p = processed_paths.get(tile_key(row - 1, col))

            temp_path = processed.with_suffix(".wrap.png")

            def repair() -> None:
                job_telemetry.set_workers(
                    job_id, cpu_active=True, cpu_label=f"Wrap close r{row}c{col}"
                )
                repair_tile_seams(
                    processed,
                    temp_path,
                    plan.overlap_px,
                    left_neighbor_path=left_p,
                    top_neighbor_path=top_p,
                )
                shutil.move(str(temp_path), str(processed))
                job_telemetry.set_workers(job_id, cpu_active=False, cpu_label="CPU idle")

            await asyncio.to_thread(repair)
            tile_paths[key] = processed
            await self._log(job_id, "cpu", f"Wrap seam closed r{row}c{col}", "")

    async def _mark_complete(
        self,
        job_id: str,
        request: MosaicJobCreate,
        plan: GridPlan,
        paths: RunPaths,
        outputs: dict,
        message: str,
    ) -> None:
        tiles = await self.store.get_tiles(job_id)
        for tile in tiles:
            tile.status = TileStatus.COMPOSITED
        await self.store.upsert_tiles(job_id, tiles)
        await self._log(job_id, "system", "Job complete", message)
        await self.store.update_job_status(
            job_id,
            JobStatus.COMPLETE,
            outputs={**outputs, "_message": message},
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        final = await self.get_progress(job_id)
        if final:
            final.status = JobStatus.COMPLETE
            final.stage = "complete"
            final.message = message
            await self._emit(final)
        logger.info("Job %s complete", job_id)
        await self._maybe_start_quality_review(job_id)

    async def _maybe_start_quality_review(self, job_id: str) -> None:
        if not self.quality:
            return
        job = await self.store.get_job(job_id)
        if not job or not job.get("run_quality_check"):
            return

        async def on_quality_progress(_report: dict) -> None:
            progress = await self.get_progress(job_id)
            if progress:
                await self._emit(progress)

        self.quality.start_background(
            job_id,
            include_ai_critique=bool(job.get("include_ai_critique")),
            on_progress=on_quality_progress,
        )

    async def cancel_job(self, job_id: str) -> bool:
        task = self._running.get(job_id)
        if not task or task.done():
            return False
        task.cancel()
        await self._log(job_id, "system", "Job cancelled", "Stop requested by user")
        await self.store.update_job_status(
            job_id,
            status=JobStatus.FAILED,
            message="Cancelled by user",
            stage="cancelled",
        )
        return True

    async def rename_job(self, job_id: str, display_name: str) -> JobProgress | None:
        name = display_name.strip()[:120]
        if not name:
            raise ValueError("Display name cannot be empty")
        await self.store.update_display_name(
            job_id,
            name,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        progress = await self.get_progress(job_id)
        if progress:
            await self._emit(progress)
        return progress

    async def trigger_quality_review(
        self,
        job_id: str,
        *,
        include_ai_critique: bool = False,
    ) -> None:
        if not self.quality:
            raise RuntimeError("Quality service unavailable")

        async def on_quality_progress(_report: dict) -> None:
            progress = await self.get_progress(job_id)
            if progress:
                await self._emit(progress)

        self.quality.start_background(
            job_id,
            include_ai_critique=include_ai_critique,
            on_progress=on_quality_progress,
        )

    async def _finalize_direct(
        self,
        job_id: str,
        request: MosaicJobCreate,
        plan: GridPlan,
        paths: RunPaths,
        source_path: Path,
        *,
        source_label: str,
    ) -> None:
        await self._log(
            job_id,
            "cpu",
            "Blueprint direct resize",
            f"Scaling {source_label} to {plan.width_px}×{plan.height_px}",
        )
        await self._refresh(
            job_id,
            request,
            plan,
            JobStatus.COMPOSITING,
            "compositing",
            f"Local resize to {plan.width_px}×{plan.height_px} (no mosaic tiles)",
        )
        feather_path = paths.final_feather_blend_path()
        hard_path = paths.final_hard_paste_path()

        def resize() -> None:
            job_telemetry.set_workers(job_id, cpu_active=True, cpu_label="Lanczos resize")
            resize_to_canvas(
                source_path, feather_path, plan.width_px, plan.height_px, enhance=False
            )
            shutil.copy2(feather_path, hard_path)
            job_telemetry.set_workers(job_id, cpu_active=False, cpu_label="CPU idle")

        await asyncio.to_thread(resize)
        outputs = {
            "blueprint": paths.relative(source_path, paths.root),
            "mosaic_hard_paste": paths.relative(hard_path, paths.root),
            "mosaic_feather_blend": paths.relative(feather_path, paths.root),
            "storage_root": paths.relative(paths.root, project_root()),
            "generation_mode": plan.generation_mode.value,
        }
        outputs = await self._attach_dzi(job_id, paths, feather_path, outputs)
        await self._mark_complete(job_id, request, plan, paths, outputs, "Blueprint direct complete")

    async def _finalize_single_enhanced(
        self,
        job_id: str,
        request: MosaicJobCreate,
        plan: GridPlan,
        paths: RunPaths,
        blueprint_path: Path,
        on_xai_event,
    ) -> None:
        row, col, seq = 0, 0, 1
        await self._log(job_id, "system", "Single enhanced tile", "One cloud tile + local resize")
        tiles = await self.store.get_tiles(job_id)
        for tile in tiles:
            if tile.row == row and tile.col == col:
                tile.status = TileStatus.CLOUD_GENERATING
        await self.store.upsert_tiles(job_id, tiles)
        await self._refresh(
            job_id,
            request,
            plan,
            JobStatus.TILING,
            "tiling",
            "Generating single 2K tile for enhanced output",
            tiles=tiles,
        )

        feather_path = paths.final_feather_blend_path()
        hard_path = paths.final_hard_paste_path()
        enhance = plan.local_upscale_factor > 1 and (
            plan.width_px > plan.base_tile_px or plan.height_px > plan.base_tile_px
        )
        canvas_ar = plan.width_px / max(1, plan.height_px)
        use_blueprint_upscale = not (0.9 <= canvas_ar <= 1.1)

        if use_blueprint_upscale:
            await self._log(
                job_id,
                "system",
                "Blueprint upscale",
                f"Non-square canvas — upscaling normalized blueprint to {plan.width_px}×{plan.height_px}",
            )
            tiles = await self.store.get_tiles(job_id)
            for tile in tiles:
                if tile.row == row and tile.col == col:
                    tile.status = TileStatus.CLOUD_DONE
            await self.store.upsert_tiles(job_id, tiles)
            await self._refresh(
                job_id,
                request,
                plan,
                JobStatus.COMPOSITING,
                "compositing",
                f"Local enhance to {plan.width_px}×{plan.height_px}",
                tiles=tiles,
            )

            def upscale_blueprint() -> None:
                job_telemetry.set_workers(
                    job_id,
                    cpu_active=True,
                    cpu_label=f"Lanczos {'+ sharpen' if enhance else 'resize'}",
                )
                resize_to_canvas(
                    blueprint_path,
                    feather_path,
                    plan.width_px,
                    plan.height_px,
                    enhance=enhance,
                )
                shutil.copy2(feather_path, hard_path)
                job_telemetry.set_workers(job_id, cpu_active=False, cpu_label="CPU idle")

            await asyncio.to_thread(upscale_blueprint)
        else:
            crop_path = paths.ref_blueprint_crop_path(seq, row, col)
            save_rgb_image(crop_blueprint_for_tile(blueprint_path, row, col, plan), crop_path)
            tile_path = paths.tile_path(seq, row, col)

            async with XAIImageEngine(self.settings, on_event=on_xai_event) as engine:
                await engine.generate_tile(
                    prompt=build_tile_prompt(
                        request.style_anchor,
                        request.prompt,
                        row,
                        col,
                        plan.rows,
                        plan.cols,
                        regions=request.regions or None,
                    ),
                    blueprint_crop_path=crop_path,
                    left_neighbor_path=None,
                    top_neighbor_path=None,
                    output_path=tile_path,
                    aspect_ratio="1:1",
                    resolution="2k",
                )

            tiles = await self.store.get_tiles(job_id)
            for tile in tiles:
                if tile.row == row and tile.col == col:
                    tile.status = TileStatus.CLOUD_DONE
                    tile.tile_path = paths.relative(tile_path, paths.root)
            await self.store.upsert_tiles(job_id, tiles)
            await self._refresh(
                job_id,
                request,
                plan,
                JobStatus.COMPOSITING,
                "compositing",
                f"Local enhance to {plan.width_px}×{plan.height_px}",
                tiles=tiles,
            )

            def resize() -> None:
                job_telemetry.set_workers(
                    job_id,
                    cpu_active=True,
                    cpu_label=f"Lanczos {'+ sharpen' if enhance else 'downscale'}",
                )
                resize_to_canvas(
                    tile_path, feather_path, plan.width_px, plan.height_px, enhance=enhance
                )
                shutil.copy2(feather_path, hard_path)
                job_telemetry.set_workers(job_id, cpu_active=False, cpu_label="CPU idle")

            await asyncio.to_thread(resize)
        outputs = {
            "blueprint": paths.relative(blueprint_path, paths.root),
            "mosaic_hard_paste": paths.relative(hard_path, paths.root),
            "mosaic_feather_blend": paths.relative(feather_path, paths.root),
            "storage_root": paths.relative(paths.root, project_root()),
            "generation_mode": plan.generation_mode.value,
        }
        outputs = await self._attach_dzi(job_id, paths, feather_path, outputs)
        await self._mark_complete(
            job_id,
            request,
            plan,
            paths,
            outputs,
            f"Single enhanced output at {plan.width_px}×{plan.height_px}",
        )

    async def _run_job(
        self,
        job_id: str,
        request: MosaicJobCreate,
        plan: GridPlan,
        paths: RunPaths,
    ) -> None:
        self._job_context[job_id] = (request, plan)
        semaphore = asyncio.Semaphore(request.max_concurrency)
        tile_paths: dict[str, Path] = {}
        processed_paths: dict[str, Path] = {}
        left_ref_paths: dict[str, Path] = {}
        top_ref_paths: dict[str, Path] = {}
        xai_lock = asyncio.Lock()
        active_xai = 0

        async def on_xai_event(action: str, detail: str) -> None:
            nonlocal active_xai
            async with xai_lock:
                if action == "request":
                    active_xai += 1
                    job_telemetry.increment_api_calls(job_id)
                elif action == "download":
                    active_xai += 1
                elif action == "response":
                    active_xai = max(0, active_xai - 1)
                elif action == "download_done":
                    active_xai = max(0, active_xai - 1)
                elif action in ("error", "rate_limit"):
                    active_xai = max(0, active_xai - 1)

                if action in ("blueprint", "tile") and active_xai > 0:
                    xai_label = detail[:48]
                elif active_xai > 0:
                    xai_label = f"xAI API ({active_xai} in flight)"
                else:
                    xai_label = "xAI idle"

                await self._set_workers(
                    job_id,
                    pulse=True,
                    xai_active=active_xai > 0,
                    xai_label=xai_label,
                )
            await self._log(job_id, "xai", detail)

        try:
            await self._log(
                job_id,
                "system",
                "Stage 1: Master blueprint",
                f"Canvas {plan.width_px}×{plan.height_px}, nearest AR for 2K generation",
            )
            await self._refresh(
                job_id,
                request,
                plan,
                JobStatus.BLUEPRINT,
                "blueprint",
                "Calling xAI /images/generations for 2K master blueprint…",
            )
            await self._set_workers(
                job_id,
                xai_active=True,
                xai_label="Blueprint generation",
            )

            blueprint_path = paths.blueprint_path()
            aspect_ratio = closest_xai_aspect_ratio(plan.width_px, plan.height_px)

            async with XAIImageEngine(self.settings, on_event=on_xai_event) as engine:
                blueprint_prompt = (
                    build_blueprint_prompt(request.style_anchor, request.prompt, request.regions)
                    if request.regions
                    else f"{request.style_anchor} {request.prompt}"
                )
                await engine.generate_blueprint(
                    prompt=blueprint_prompt,
                    output_path=blueprint_path,
                    aspect_ratio=aspect_ratio,
                    resolution="2k",
                )

            await self._set_workers(job_id, xai_active=False, xai_label="xAI idle")
            blueprint_img = ensure_rgb_image(blueprint_path)
            normalized = normalize_blueprint_for_plan(blueprint_img, plan)
            save_rgb_image(normalized, blueprint_path)
            blueprint_rel = paths.relative(blueprint_path, paths.root)
            await self._log(
                job_id,
                "system",
                "Blueprint saved",
                f"{blueprint_rel} — normalized to {normalized.width}×{normalized.height} "
                f"(canvas {plan.width_px}×{plan.height_px})",
            )
            await self._refresh(
                job_id,
                request,
                plan,
                JobStatus.TILING,
                "tiling",
                plan.strategy_message,
                outputs={
                    "blueprint": blueprint_rel,
                    "storage_root": paths.relative(paths.root, project_root()),
                },
            )

            if plan.generation_mode == GenerationMode.BLUEPRINT_DIRECT:
                await self._finalize_direct(
                    job_id, request, plan, paths, blueprint_path, source_label="blueprint"
                )
                return

            if plan.generation_mode == GenerationMode.SINGLE_ENHANCED:
                await self._finalize_single_enhanced(
                    job_id, request, plan, paths, blueprint_path, on_xai_event
                )
                return

            async with XAIImageEngine(self.settings, on_event=on_xai_event) as engine:
                seq_counter = 1
                for wave_index, wave in enumerate(wavefront_order(plan.rows, plan.cols)):
                    await self._log(
                        job_id,
                        "system",
                        f"Wavefront wave {wave_index + 1}",
                        f"Tiles: {wave}",
                    )

                    async def process_tile(seq: int, row: int, col: int) -> None:
                        key = tile_key(row, col)
                        tiles = await self.store.get_tiles(job_id)
                        for tile in tiles:
                            if tile.row == row and tile.col == col:
                                tile.status = TileStatus.CLOUD_GENERATING
                        await self.store.upsert_tiles(job_id, tiles)
                        await self._refresh(
                            job_id,
                            request,
                            plan,
                            JobStatus.TILING,
                            "tiling",
                            f"xAI tile {seq}/{plan.tile_count} — r{row}c{col}: preparing context images",
                            tiles=tiles,
                        )

                        await self._set_workers(
                            job_id,
                            cpu_active=True,
                            cpu_label=f"Crop/refs r{row}c{col}",
                        )
                        crop_path = paths.ref_blueprint_crop_path(seq, row, col)
                        save_rgb_image(
                            crop_blueprint_for_tile(blueprint_path, row, col, plan), crop_path
                        )

                        left_ref = left_ref_paths.get(tile_key(row, col - 1)) if col > 0 else None
                        top_ref = top_ref_paths.get(tile_key(row - 1, col)) if row > 0 else None
                        tile_path = paths.tile_path(seq, row, col)
                        left_processed = processed_paths.get(tile_key(row, col - 1)) if col > 0 else None
                        top_processed = processed_paths.get(tile_key(row - 1, col)) if row > 0 else None
                        processed_path = paths.processed_tile_path(seq, row, col)
                        max_attempts = 1 + self.settings.max_tile_retries

                        for attempt in range(max_attempts):
                            if attempt > 0:
                                await self._log(
                                    job_id,
                                    "system",
                                    f"Retry tile r{row}c{col}",
                                    f"Seam QA failed — attempt {attempt + 1}/{max_attempts}",
                                )
                            await self._set_workers(
                                job_id,
                                xai_active=True,
                                xai_label=f"Tile r{row}c{col} → xAI"
                                + (f" (retry {attempt})" if attempt else ""),
                            )
                            async with semaphore:
                                await engine.generate_tile(
                                    prompt=build_tile_prompt(
                                        request.style_anchor,
                                        request.prompt,
                                        row,
                                        col,
                                        plan.rows,
                                        plan.cols,
                                        regions=request.regions or None,
                                    ),
                                    blueprint_crop_path=crop_path,
                                    left_neighbor_path=left_ref,
                                    top_neighbor_path=top_ref,
                                    output_path=tile_path,
                                    aspect_ratio="1:1",
                                    resolution="2k",
                                )

                            await self._set_workers(
                                job_id,
                                cpu_active=True,
                                cpu_label=f"Overlap strips r{row}c{col}",
                            )
                            left_strip = paths.ref_left_strip_path(seq, row, col)
                            top_strip = paths.ref_top_strip_path(seq, row, col)
                            save_overlap_reference(
                                tile_path, "right", plan.overlap_px, left_strip, self.settings.placeholder_size
                            )
                            save_overlap_reference(
                                tile_path, "bottom", plan.overlap_px, top_strip, self.settings.placeholder_size
                            )
                            left_ref_paths[key] = left_strip
                            top_ref_paths[key] = top_strip

                            tiles = await self.store.get_tiles(job_id)
                            for tile in tiles:
                                if tile.row == row and tile.col == col:
                                    tile.status = TileStatus.LOCAL_PROCESSING
                            await self.store.upsert_tiles(job_id, tiles)

                            await self._refine_cloud_tile(
                                job_id,
                                plan,
                                tile_path,
                                processed_path,
                                row,
                                col,
                                left_processed,
                                top_processed,
                            )

                            if not left_processed and not top_processed:
                                break
                            worst_mse, qa_ok, qa_notes = score_tile_seams(
                                processed_path,
                                plan.overlap_px,
                                left_processed,
                                top_processed,
                                threshold=self.settings.overlap_mse_threshold,
                            )
                            if qa_ok:
                                if qa_notes:
                                    await self._log(
                                        job_id,
                                        "cpu",
                                        f"Seam QA pass r{row}c{col}",
                                        "; ".join(qa_notes),
                                    )
                                break
                            if attempt >= max_attempts - 1:
                                await self._log(
                                    job_id,
                                    "system",
                                    f"Seam QA warn r{row}c{col}",
                                    f"worst MSE {worst_mse:.0f} — keeping best effort",
                                )

                        processed_paths[key] = processed_path
                        tile_paths[key] = processed_path

                        tiles = await self.store.get_tiles(job_id)
                        for tile in tiles:
                            if tile.row == row and tile.col == col:
                                tile.status = TileStatus.CLOUD_DONE
                                tile.tile_path = paths.relative(processed_path, paths.root)
                        await self.store.upsert_tiles(job_id, tiles)
                        await self._refresh(
                            job_id,
                            request,
                            plan,
                            JobStatus.TILING,
                            "tiling",
                            f"Tile {seq}/{plan.tile_count} complete — r{row}c{col} saved",
                            tiles=tiles,
                        )

                    await asyncio.gather(
                        *[process_tile(seq_counter + i, row, col) for i, (row, col) in enumerate(wave)]
                    )
                    seq_counter += len(wave)

            await self._closing_pass_wrap(
                job_id, request, plan, processed_paths, tile_paths
            )

            await self._log(job_id, "system", "Stage 4: Compositing", "Merging tiles into master canvas")
            await self._refresh(
                job_id,
                request,
                plan,
                JobStatus.COMPOSITING,
                "compositing",
                "CPU/GPU compositing — feather blend + BigTIFF export",
            )

            scratch = paths.working_dir / "canvas.dat"
            feather_path = paths.final_feather_blend_path()
            hard_path = paths.final_hard_paste_path()
            bigtiff_path = paths.final_dir / "04_master.bigtiff"
            gpu_available = await is_comfyui_available(self.settings)

            def compose() -> None:
                job_telemetry.set_workers(
                    job_id,
                    cpu_active=True,
                    cpu_label="Stitching tiles (NumPy)",
                    gpu_active=gpu_available,
                    gpu_label="CUDA blend" if gpu_available else "GPU idle",
                )
                stitch_all_tiles(tile_paths, plan, hard_path, blend_mode="hard")
                stitch_all_tiles_memmap(
                    tile_paths,
                    plan,
                    scratch,
                    feather_path,
                    bigtiff_path=bigtiff_path,
                )

            await self._set_workers(
                job_id,
                cpu_active=True,
                cpu_label="Compositing…",
                gpu_active=gpu_available,
                gpu_label="Memmap + optional CUDA" if gpu_available else "CPU compositor",
            )
            await asyncio.to_thread(compose)
            await self._set_workers(
                job_id,
                cpu_active=False,
                cpu_label="CPU idle",
                gpu_active=False,
                gpu_label="GPU idle",
            )
            await self._log(job_id, "cpu", "Composite complete", paths.relative(feather_path, paths.root))

            outputs = {
                "blueprint": paths.relative(blueprint_path, paths.root),
                "mosaic_hard_paste": paths.relative(hard_path, paths.root),
                "mosaic_feather_blend": paths.relative(feather_path, paths.root),
                "master_bigtiff": paths.relative(bigtiff_path, paths.root),
                "storage_root": paths.relative(paths.root, project_root()),
                "comfyui_available": gpu_available,
                "generation_mode": plan.generation_mode.value,
            }
            outputs = await self._attach_dzi(job_id, paths, feather_path, outputs)

            tiles = await self.store.get_tiles(job_id)
            for tile in tiles:
                tile.status = TileStatus.COMPOSITED
            await self.store.upsert_tiles(job_id, tiles)

            await self._mark_complete(
                job_id,
                request,
                plan,
                paths,
                outputs,
                "Mosaic generation complete",
            )

        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            job_telemetry.set_workers(
                job_id,
                xai_active=False,
                cpu_active=False,
                gpu_active=False,
                xai_label="Error",
                cpu_label="Error",
                gpu_label="Error",
            )
            await self._log(job_id, "system", "Job failed", str(exc))
            await self.store.update_job_status(
                job_id,
                JobStatus.FAILED,
                error=str(exc),
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            failed = await self.get_progress(job_id)
            if failed:
                failed.status = JobStatus.FAILED
                failed.error = str(exc)
                failed.stage = "failed"
                failed.message = f"Failed: {exc}"
                await self._emit(failed)
