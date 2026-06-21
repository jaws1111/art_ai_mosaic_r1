"""Phase 0/1 compositor: stitch cloud tiles with overlap-aware placement."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from app.core.grid_math import GridPlan, parse_tile_key
from app.services.blend_utils import merge_tile_into_canvas
from app.services.image_utils import ensure_rgb_image, tile_origin


class SimpleCompositor:
    def __init__(self, plan: GridPlan, blend_mode: str = "feather") -> None:
        if blend_mode not in {"feather", "hard"}:
            raise ValueError("blend_mode must be 'feather' or 'hard'")
        self.plan = plan
        self.blend_mode = blend_mode
        self.canvas = np.zeros((plan.height_px, plan.width_px, 3), dtype=np.uint8)

    def stitch_tile(self, tile_path: Path, row: int, col: int) -> None:
        tile = ensure_rgb_image(tile_path)
        if tile.size != (self.plan.tile_effective, self.plan.tile_effective):
            tile = tile.resize(
                (self.plan.tile_effective, self.plan.tile_effective),
                Image.Resampling.LANCZOS,
            )
        tile_array = np.asarray(tile, dtype=np.uint8)
        x, y = tile_origin(row, col, self.plan)
        tile_h, tile_w = tile_array.shape[:2]
        visible_w = min(tile_w, self.plan.width_px - x)
        visible_h = min(tile_h, self.plan.height_px - y)

        if self.blend_mode == "hard":
            self.canvas[y : y + visible_h, x : x + visible_w] = tile_array[:visible_h, :visible_w]
            return

        merge_tile_into_canvas(
            self.canvas,
            tile_array,
            x,
            y,
            overlap_px=self.plan.overlap_px,
            row=row,
            col=col,
        )

    def save(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(self.canvas, mode="RGB").save(output_path, format="PNG")
        return output_path


def stitch_all_tiles(
    tile_paths: dict[str, Path],
    plan: GridPlan,
    output_path: Path,
    blend_mode: str = "feather",
) -> Path:
    compositor = SimpleCompositor(plan, blend_mode=blend_mode)
    for key in sorted(tile_paths.keys(), key=lambda value: parse_tile_key(value)):
        row, col = parse_tile_key(key)
        compositor.stitch_tile(tile_paths[key], row, col)
    return compositor.save(output_path)
