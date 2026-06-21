"""Memmap-backed canvas compositor with optional CUDA blending and BigTIFF export."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PIL import Image

from app.core.grid_math import GridPlan, parse_tile_key
from app.services.blend_utils import merge_tile_into_canvas, smooth_ramp
from app.services.image_utils import ensure_rgb_image, tile_origin

logger = logging.getLogger(__name__)

try:
    import torch

    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


class CanvasCompositor:
    """Disk-backed canvas for large mosaics; never holds full image in RAM."""

    def __init__(self, plan: GridPlan, scratch_path: Path, use_cuda: bool = True) -> None:
        self.plan = plan
        self.scratch_path = scratch_path
        self.use_cuda = use_cuda and HAS_TORCH and torch.cuda.is_available()
        scratch_path.parent.mkdir(parents=True, exist_ok=True)
        self._mmap = np.memmap(
            scratch_path,
            dtype=np.uint8,
            mode="w+",
            shape=(plan.height_px, plan.width_px, 3),
        )
        self._mmap[:] = 0

    @property
    def canvas(self) -> np.ndarray:
        return self._mmap

    def stitch_tile(self, tile_path: Path, row: int, col: int) -> None:
        tile = ensure_rgb_image(tile_path)
        if tile.size != (self.plan.tile_effective, self.plan.tile_effective):
            tile = tile.resize(
                (self.plan.tile_effective, self.plan.tile_effective),
                Image.Resampling.LANCZOS,
            )
        tile_array = np.asarray(tile, dtype=np.uint8)
        x, y = tile_origin(row, col, self.plan)

        if self.use_cuda:
            self._stitch_cuda(tile_array, x, y, row, col)
        else:
            merge_tile_into_canvas(
                self._mmap,
                tile_array,
                x,
                y,
                overlap_px=self.plan.overlap_px,
                row=row,
                col=col,
            )
        self._mmap.flush()

    def _stitch_cuda(self, tile: np.ndarray, dest_x: int, dest_y: int, row: int, col: int) -> None:
        assert HAS_TORCH
        tile_h, tile_w = tile.shape[:2]
        visible_w = min(tile_w, self.plan.width_px - dest_x)
        visible_h = min(tile_h, self.plan.height_px - dest_y)
        overlap = min(self.plan.overlap_px, visible_w, visible_h)

        region = self._mmap[dest_y : dest_y + visible_h, dest_x : dest_x + visible_w]
        incoming = torch.from_numpy(tile[:visible_h, :visible_w].copy()).cuda().float()
        existing = torch.from_numpy(region.copy()).cuda().float()
        merged = incoming.clone()

        if col > 0 and overlap > 0:
            ramp = torch.from_numpy(smooth_ramp(overlap)).cuda().view(1, -1, 1)
            merged[:, :overlap, :] = existing[:, :overlap, :] * (1 - ramp) + merged[:, :overlap, :] * ramp

        if row > 0 and overlap > 0:
            ramp = torch.from_numpy(smooth_ramp(overlap)).cuda().view(-1, 1, 1)
            top_existing = existing[:overlap, :, :]
            top_merged = merged[:overlap, :, :]
            merged[:overlap, :, :] = top_existing * (1 - ramp) + top_merged * ramp

        self._mmap[dest_y : dest_y + visible_h, dest_x : dest_x + visible_w] = (
            merged.clamp(0, 255).byte().cpu().numpy()
        )

    def save_png(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(np.asarray(self._mmap), mode="RGB").save(output_path, format="PNG")
        return output_path

    def save_bigtiff(self, output_path: Path) -> Path:
        import tifffile

        output_path.parent.mkdir(parents=True, exist_ok=True)
        data = np.asarray(self._mmap)
        tifffile.imwrite(
            output_path,
            data,
            photometric="rgb",
            tile=(512, 512),
            compression="zlib",
            bigtiff=True,
        )
        logger.info("Saved BigTIFF to %s", output_path)
        return output_path

    def close(self) -> None:
        del self._mmap


def stitch_all_tiles_memmap(
    tile_paths: dict[str, Path],
    plan: GridPlan,
    scratch_path: Path,
    png_path: Path,
    bigtiff_path: Path | None = None,
) -> dict[str, Path]:
    compositor = CanvasCompositor(plan, scratch_path)
    try:
        for key in sorted(tile_paths.keys(), key=lambda value: parse_tile_key(value)):
            row, col = parse_tile_key(key)
            compositor.stitch_tile(tile_paths[key], row, col)
        outputs = {"png": compositor.save_png(png_path)}
        if bigtiff_path is not None:
            outputs["bigtiff"] = compositor.save_bigtiff(bigtiff_path)
        return outputs
    finally:
        compositor.close()
