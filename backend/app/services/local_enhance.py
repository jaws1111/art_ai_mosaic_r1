"""Local image resize/upscale for single-tile and blueprint-direct modes."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter

from app.services.image_utils import ensure_rgb_image, save_rgb_image


def resize_to_canvas(
    source_path: Path,
    output_path: Path,
    width_px: int,
    height_px: int,
    *,
    enhance: bool = False,
) -> Path:
    """Resize (up or down) with high-quality Lanczos. Optional mild sharpen on upscale."""
    image = ensure_rgb_image(source_path)
    if enhance and (width_px > image.width or height_px > image.height):
        image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=80, threshold=2))
    resized = image.resize((width_px, height_px), Image.Resampling.LANCZOS)
    return save_rgb_image(resized, output_path)


def upscale_factor_for_target(source_px: int, target_px: int) -> int:
    if source_px <= 0 or target_px <= source_px:
        return 1
    return max(1, min(4, (target_px + source_px - 1) // source_px))
