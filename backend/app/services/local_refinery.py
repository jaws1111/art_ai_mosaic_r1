"""Stage 3 local refinery: upscale tiles + seam harmonization (Phase 1.4–1.5)."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from PIL import Image, ImageFilter

from app.core.config import Settings
from app.core.grid_math import GridPlan
from app.services.image_utils import ensure_rgb_image, save_rgb_image
from app.services.seam_repair import repair_tile_seams

logger = logging.getLogger(__name__)


def upscale_tile_lanczos(
    input_path: Path,
    output_path: Path,
    target_px: int,
    *,
    sharpen: bool = True,
) -> Path:
    """CPU fallback upscale/downscale to exact tile_effective size."""
    image = ensure_rgb_image(input_path)
    if sharpen and target_px > max(image.width, image.height):
        image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=70, threshold=2))
    resized = image.resize((target_px, target_px), Image.Resampling.LANCZOS)
    return save_rgb_image(resized, output_path)


def refine_tile_sync(
    input_path: Path,
    output_path: Path,
    plan: GridPlan,
    *,
    left_neighbor_path: Path | None = None,
    top_neighbor_path: Path | None = None,
    settings: Settings | None = None,
) -> Path:
    """
    Upscale cloud tile to tile_effective, harmonize seams, write processed PNG.

    ComfyUI upscale is attempted by the async wrapper when GPU service is available.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    target_px = plan.tile_effective
    working = output_path.with_suffix(".work.png")

    image = ensure_rgb_image(input_path)
    already_sized = max(image.width, image.height) == target_px and image.width == image.height

    if already_sized:
        shutil.copy2(input_path, working)
    elif plan.upscale_factor > 1:
        upscale_tile_lanczos(input_path, working, target_px, sharpen=True)
    else:
        save_rgb_image(
            image.resize((target_px, target_px), Image.Resampling.LANCZOS),
            working,
        )

    if left_neighbor_path or top_neighbor_path:
        repair_tile_seams(
            working,
            output_path,
            plan.overlap_px,
            left_neighbor_path=left_neighbor_path,
            top_neighbor_path=top_neighbor_path,
        )
        if working.exists() and working != output_path:
            working.unlink(missing_ok=True)
    else:
        shutil.move(str(working), str(output_path))

    return output_path
