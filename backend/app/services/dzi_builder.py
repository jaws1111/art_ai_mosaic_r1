"""Deep Zoom Image (DZI) pyramid builder for OpenSeadragon (Phase 1.6)."""

from __future__ import annotations

import logging
import math
from pathlib import Path

from PIL import Image

from app.services.image_utils import ensure_rgb_image

logger = logging.getLogger(__name__)

TILE_SIZE = 256
OVERLAP = 1


def _num_levels(width: int, height: int) -> int:
    return int(math.ceil(math.log2(max(width, height, 1)))) + 1


def build_dzi(source_path: Path, output_dir: Path, name: str = "mosaic") -> Path:
    """
    Build a Microsoft Deep Zoom pyramid beside `{name}.dzi`.

    Level 0 is lowest resolution; highest level is full size.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    image = ensure_rgb_image(source_path)
    width, height = image.size
    max_level = _num_levels(width, height) - 1

    dzi_path = output_dir / f"{name}.dzi"
    dzi_path.write_text(
        "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<Image xmlns="http://schemas.microsoft.com/deepzoom/2008"',
                '  Format="jpg"',
                f'  Overlap="{OVERLAP}"',
                f'  TileSize="{TILE_SIZE}">',
                f'  <Size Width="{width}" Height="{height}"/>',
                "</Image>",
            ]
        ),
        encoding="utf-8",
    )

    files_root = output_dir / f"{name}_files"
    for level in range(max_level + 1):
        scale = 0.5 ** (max_level - level)
        level_w = max(1, int(math.ceil(width * scale)))
        level_h = max(1, int(math.ceil(height * scale)))
        level_img = (
            image
            if level_w == width and level_h == height
            else image.resize((level_w, level_h), Image.Resampling.LANCZOS)
        )

        level_dir = files_root / str(level)
        level_dir.mkdir(parents=True, exist_ok=True)
        cols = int(math.ceil(level_w / TILE_SIZE))
        rows = int(math.ceil(level_h / TILE_SIZE))

        for row in range(rows):
            for col in range(cols):
                left = col * TILE_SIZE
                top = row * TILE_SIZE
                right = min(left + TILE_SIZE, level_w)
                bottom = min(top + TILE_SIZE, level_h)
                tile = level_img.crop((left, top, right, bottom))
                if tile.size != (TILE_SIZE, TILE_SIZE):
                    padded = Image.new("RGB", (TILE_SIZE, TILE_SIZE), color=(0, 0, 0))
                    padded.paste(tile, (0, 0))
                    tile = padded
                tile.save(level_dir / f"{col}_{row}.jpg", format="JPEG", quality=85, optimize=True)

    logger.info("Built DZI pyramid at %s (%dx%d, %d levels)", dzi_path, width, height, max_level + 1)
    return dzi_path
