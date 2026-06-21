"""Overlap blending utilities for tile compositing."""

from __future__ import annotations

import numpy as np


def linear_ramp(length: int, start: float = 0.0, end: float = 1.0) -> np.ndarray:
    if length <= 0:
        return np.array([], dtype=np.float32)
    if length == 1:
        return np.array([(start + end) / 2.0], dtype=np.float32)
    return np.linspace(start, end, length, dtype=np.float32)


def smooth_ramp(length: int) -> np.ndarray:
    """Cosine ease for softer seam transitions (Phase 1.5)."""
    if length <= 0:
        return np.array([], dtype=np.float32)
    t = linear_ramp(length)
    return (0.5 - 0.5 * np.cos(t * np.pi)).astype(np.float32)


def merge_tile_into_canvas(
    canvas: np.ndarray,
    tile: np.ndarray,
    dest_x: int,
    dest_y: int,
    overlap_px: int,
    row: int,
    col: int,
) -> None:
    """
    Place a tile onto the canvas with correct overlap blending.

    Only the overlap bands are feather-blended; non-overlap regions from the
    incoming tile replace the destination (standard mosaic stitch).
    """
    tile_h, tile_w = tile.shape[:2]
    canvas_h, canvas_w = canvas.shape[:2]

    visible_w = min(tile_w, canvas_w - dest_x)
    visible_h = min(tile_h, canvas_h - dest_y)
    if visible_w <= 0 or visible_h <= 0:
        return

    tile = tile[:visible_h, :visible_w]
    region = canvas[dest_y : dest_y + visible_h, dest_x : dest_x + visible_w]
    overlap = min(overlap_px, visible_w, visible_h)

    merged = tile.astype(np.float32)
    existing = region.astype(np.float32)

    if col > 0 and overlap > 0:
        ramp = smooth_ramp(overlap)[None, :, None]
        merged[:, :overlap, :] = existing[:, :overlap, :] * (1.0 - ramp) + merged[:, :overlap, :] * ramp

    if row > 0 and overlap > 0:
        ramp = smooth_ramp(overlap)[:, None, None]
        top_existing = existing[:overlap, :, :]
        top_merged = merged[:overlap, :, :]
        merged[:overlap, :, :] = top_existing * (1.0 - ramp) + top_merged * ramp

    canvas[dest_y : dest_y + visible_h, dest_x : dest_x + visible_w] = np.clip(
        merged, 0, 255
    ).astype(np.uint8)
