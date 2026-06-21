"""Canvas plan preview (no API calls)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.grid_math import CanvasFormat, GridPlanRequest, build_grid_plan, wrap_flags_for_canvas


class PlanPreviewRequest(BaseModel):
    canvas: CanvasFormat
    upscale_factor: int = Field(default=2, ge=1, le=4)
    overlap_fraction: float = Field(default=0.25, gt=0.0, lt=1.0)
    base_tile_px: int = 2048


class PlanPreviewResponse(BaseModel):
    generation_mode: str
    strategy_message: str
    rows: int
    cols: int
    tile_count: int
    tile_effective: int
    local_upscale_factor: int
    est_cloud_calls: int
    est_cost_usd: float
    use_mosaic_stitch: bool
    width_px: int
    height_px: int
    crop_upscale_ratio: float = 1.0
    crop_quality_warning: str | None = None


def preview_plan(request: PlanPreviewRequest) -> PlanPreviewResponse:
    wrap_h, wrap_v = wrap_flags_for_canvas(
        request.canvas.mode,
        getattr(request.canvas, "wraparound", False),
    )
    plan = build_grid_plan(
        GridPlanRequest(
            width_px=request.canvas.width_px,
            height_px=request.canvas.height_px,
            base_tile_px=request.base_tile_px,
            upscale_factor=request.upscale_factor,
            overlap_fraction=request.overlap_fraction,
            wrap_horizontal=wrap_h,
            wrap_vertical=wrap_v,
        )
    )
    if plan.generation_mode.value == "blueprint_direct":
        cloud_calls = 1
    elif plan.generation_mode.value == "single_enhanced":
        cloud_calls = 2  # blueprint + one tile
    else:
        cloud_calls = 1 + plan.tile_count

    return PlanPreviewResponse(
        generation_mode=plan.generation_mode.value,
        strategy_message=plan.strategy_message,
        rows=plan.rows,
        cols=plan.cols,
        tile_count=plan.tile_count,
        tile_effective=plan.tile_effective,
        local_upscale_factor=plan.local_upscale_factor,
        est_cloud_calls=cloud_calls,
        est_cost_usd=round(0.026 * cloud_calls, 2),
        use_mosaic_stitch=plan.use_mosaic_stitch,
        width_px=plan.width_px,
        height_px=plan.height_px,
        crop_upscale_ratio=plan.crop_upscale_ratio,
        crop_quality_warning=plan.crop_quality_warning,
    )
