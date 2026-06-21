"""Image helpers: placeholders, blueprint crops, overlap strips, encoding."""

from __future__ import annotations

import base64
import io
from pathlib import Path

import numpy as np
from PIL import Image

from app.core.grid_math import GridPlan, TileCoord


def ensure_rgb_image(path: Path) -> Image.Image:
    with Image.open(path) as img:
        return img.convert("RGB")


def save_rgb_image(image: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")
    return path


def create_black_placeholder(size: int) -> Image.Image:
    return Image.new("RGB", (size, size), color=(0, 0, 0))


def ensure_placeholder_file(path: Path, size: int) -> Path:
    if not path.exists():
        save_rgb_image(create_black_placeholder(size), path)
    return path


def image_to_data_url(path: Path) -> str:
    with path.open("rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")
    suffix = path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64,{encoded}"


def normalize_blueprint_for_plan(
    blueprint: Image.Image,
    plan: GridPlan,
    long_edge: int = 2048,
) -> Image.Image:
    """Reproject blueprint to exact canvas aspect (xAI AR may differ from target canvas)."""
    if plan.width_px >= plan.height_px:
        target_w = long_edge
        target_h = max(1, round(long_edge * plan.height_px / plan.width_px))
    else:
        target_h = long_edge
        target_w = max(1, round(long_edge * plan.width_px / plan.height_px))
    if blueprint.size == (target_w, target_h):
        return blueprint
    return blueprint.resize((target_w, target_h), Image.Resampling.LANCZOS)


def canvas_tile_rect(row: int, col: int, plan: GridPlan) -> tuple[int, int, int, int]:
    """Pixel rect on the target canvas covered by this mosaic tile."""
    x = col * plan.stride
    y = row * plan.stride
    w = min(plan.tile_effective, plan.width_px - x)
    h = min(plan.tile_effective, plan.height_px - y)
    return x, y, w, h


def pad_to_square(
    image: Image.Image,
    size: int,
    fill: tuple[int, int, int] = (0, 0, 0),
) -> Image.Image:
    """Letterbox a crop into a square without stretching (for xAI 1:1 tile input)."""
    w, h = image.size
    if w == h == size:
        return image
    if w > size or h > size:
        scale = min(size / w, size / h)
        w, h = max(1, int(w * scale)), max(1, int(h * scale))
        image = image.resize((w, h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (size, size), fill)
    canvas.paste(image, ((size - w) // 2, (size - h) // 2))
    return canvas


def crop_blueprint_for_tile(
    blueprint_path: Path,
    row: int,
    col: int,
    plan: GridPlan,
) -> Image.Image:
    """Map canvas tile footprint to blueprint pixels (blueprint must match canvas aspect)."""
    blueprint = ensure_rgb_image(blueprint_path)
    x, y, tw, th = canvas_tile_rect(row, col, plan)
    bx0 = int(x * blueprint.width / plan.width_px)
    by0 = int(y * blueprint.height / plan.height_px)
    bx1 = int((x + tw) * blueprint.width / plan.width_px)
    by1 = int((y + th) * blueprint.height / plan.height_px)
    bx1 = max(bx0 + 1, bx1)
    by1 = max(by0 + 1, by1)
    crop = blueprint.crop((bx0, by0, bx1, by1))
    if crop.width == crop.height:
        return crop.resize((plan.base_tile_px, plan.base_tile_px), Image.Resampling.LANCZOS)
    fitted = crop.resize(
        (
            max(1, int(plan.base_tile_px * crop.width / max(crop.width, crop.height))),
            max(1, int(plan.base_tile_px * crop.height / max(crop.width, crop.height))),
        ),
        Image.Resampling.LANCZOS,
    )
    return pad_to_square(fitted, plan.base_tile_px)


def extract_overlap_strip(
    tile_path: Path,
    direction: str,
    strip_px: int,
) -> Image.Image:
    tile = ensure_rgb_image(tile_path)
    strip_px = min(strip_px, tile.width, tile.height)
    if direction == "right":
        return tile.crop((tile.width - strip_px, 0, tile.width, tile.height))
    if direction == "bottom":
        return tile.crop((0, tile.height - strip_px, tile.width, tile.height))
    raise ValueError(f"Unsupported overlap direction: {direction}")


def save_overlap_reference(
    tile_path: Path,
    direction: str,
    strip_px: int,
    output_path: Path,
    target_size: int,
) -> Path:
    strip = extract_overlap_strip(tile_path, direction, strip_px)
    strip = strip.resize((target_size, target_size), Image.Resampling.LANCZOS)
    return save_rgb_image(strip, output_path)


def tile_origin(row: int, col: int, plan: GridPlan) -> TileCoord:
    x = col * plan.stride
    y = row * plan.stride
    return x, y


def build_comparison_image(left: Path, right: Path, output_path: Path, labels: tuple[str, str]) -> Path:
    left_img = ensure_rgb_image(left)
    right_img = ensure_rgb_image(right)
    height = max(left_img.height, right_img.height)

    def pad_to_height(image: Image.Image) -> Image.Image:
        if image.height == height:
            return image
        canvas = Image.new("RGB", (image.width, height), color=(20, 20, 20))
        canvas.paste(image, (0, 0))
        return canvas

    left_img = pad_to_height(left_img)
    right_img = pad_to_height(right_img)
    gap = 12
    header = 36
    canvas = Image.new("RGB", (left_img.width + right_img.width + gap, height + header), color=(20, 20, 20))
    canvas.paste(left_img, (0, header))
    canvas.paste(right_img, (left_img.width + gap, header))

    # Simple text labels via tiny bitmap is overkill; filenames in output path are enough for phase 0.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="PNG")
    return output_path


def numpy_feather_blend(existing: np.ndarray, incoming: np.ndarray, axis: str) -> np.ndarray:
    """Blend overlap between two same-sized RGB arrays along horizontal or vertical axis."""
    if existing.shape != incoming.shape:
        raise ValueError("Feather blend arrays must share shape.")

    height, width, _ = existing.shape
    overlap = width // 4 if axis == "horizontal" else height // 4
    overlap = max(1, overlap)
    result = incoming.copy()

    if axis == "horizontal":
        ramp = np.linspace(1.0, 0.0, overlap, dtype=np.float32)[:, None, None]
        blend_region = (
            incoming[:, :overlap].astype(np.float32) * ramp
            + existing[:, :overlap].astype(np.float32) * (1.0 - ramp)
        )
        result[:, :overlap] = np.clip(blend_region, 0, 255).astype(np.uint8)
    else:
        ramp = np.linspace(1.0, 0.0, overlap, dtype=np.float32)[:, None, None]
        blend_region = (
            incoming[:overlap, :].astype(np.float32) * ramp
            + existing[:overlap, :].astype(np.float32) * (1.0 - ramp)
        )
        result[:overlap, :] = np.clip(blend_region, 0, 255).astype(np.uint8)

    return result
