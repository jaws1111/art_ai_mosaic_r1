"""Overlap similarity QA for seam drift detection (Phase 3)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from app.services.image_utils import ensure_rgb_image

# Mean squared error in 0–255 space; above this suggests visible seam drift.
DEFAULT_MSE_THRESHOLD = 900.0


def _edge_band(array: np.ndarray, edge: str, overlap_px: int) -> np.ndarray:
    overlap = min(overlap_px, array.shape[0], array.shape[1])
    if overlap <= 0:
        return array[:0, :0, :]
    if edge == "left":
        return array[:, :overlap, :]
    if edge == "right":
        return array[:, -overlap:, :]
    if edge == "top":
        return array[:overlap, :, :]
    if edge == "bottom":
        return array[-overlap:, :, :]
    raise ValueError(f"Unknown edge: {edge}")


def overlap_mse(
    tile_path: Path,
    neighbor_path: Path,
    *,
    tile_edge: str,
    neighbor_edge: str,
    overlap_px: int,
) -> float:
    """Compare overlap bands between two tiles. Lower is better."""
    tile = np.asarray(ensure_rgb_image(tile_path), dtype=np.float32)
    neighbor = np.asarray(ensure_rgb_image(neighbor_path), dtype=np.float32)
    band_a = _edge_band(tile, tile_edge, overlap_px)
    band_b = _edge_band(neighbor, neighbor_edge, overlap_px)
    if band_a.size == 0 or band_b.size == 0:
        return 0.0
    if band_a.shape != band_b.shape:
        from PIL import Image

        img_b = Image.fromarray(band_b.astype(np.uint8))
        img_b = img_b.resize((band_a.shape[1], band_a.shape[0]), Image.Resampling.LANCZOS)
        band_b = np.asarray(img_b, dtype=np.float32)
    return float(np.mean((band_a - band_b) ** 2))


def score_tile_seams(
    tile_path: Path,
    overlap_px: int,
    left_neighbor_path: Path | None = None,
    top_neighbor_path: Path | None = None,
    *,
    threshold: float = DEFAULT_MSE_THRESHOLD,
) -> tuple[float, bool, list[str]]:
    """
    Return worst MSE, pass/fail, and human-readable edge notes.
    """
    scores: list[tuple[str, float]] = []
    if left_neighbor_path and left_neighbor_path.is_file():
        mse = overlap_mse(
            tile_path,
            left_neighbor_path,
            tile_edge="left",
            neighbor_edge="right",
            overlap_px=overlap_px,
        )
        scores.append((f"left edge MSE={mse:.0f}", mse))
    if top_neighbor_path and top_neighbor_path.is_file():
        mse = overlap_mse(
            tile_path,
            top_neighbor_path,
            tile_edge="top",
            neighbor_edge="bottom",
            overlap_px=overlap_px,
        )
        scores.append((f"top edge MSE={mse:.0f}", mse))

    if not scores:
        return 0.0, True, []

    worst = max(scores, key=lambda item: item[1])
    notes = [label for label, _ in scores]
    return worst[1], worst[1] <= threshold, notes
