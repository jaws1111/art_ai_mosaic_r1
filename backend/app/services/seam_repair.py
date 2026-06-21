"""Local seam harmonization (Phase 1.5) — color-match overlap bands before compositing."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from app.services.image_utils import ensure_rgb_image, save_rgb_image


def _match_band_to_reference(source: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Linear per-channel mean/std transfer from reference onto source band."""
    matched = source.astype(np.float32)
    ref = reference.astype(np.float32)
    for channel in range(3):
        s_mean = float(source[:, :, channel].mean())
        s_std = float(source[:, :, channel].std()) + 1e-6
        r_mean = float(ref[:, :, channel].mean())
        r_std = float(ref[:, :, channel].std()) + 1e-6
        matched[:, :, channel] = (matched[:, :, channel] - s_mean) * (r_std / s_std) + r_mean
    return np.clip(matched, 0, 255).astype(np.uint8)


def harmonize_left_edge(tile: np.ndarray, left_neighbor: np.ndarray, overlap_px: int) -> np.ndarray:
    """Adjust the left overlap band of tile to match the right edge of the left neighbor."""
    overlap = min(overlap_px, tile.shape[1], left_neighbor.shape[1])
    if overlap <= 0:
        return tile

    result = tile.copy()
    neighbor_band = left_neighbor[:, -overlap:, :]
    tile_band = tile[:, :overlap, :]
    if neighbor_band.shape != tile_band.shape:
        neighbor_img = Image.fromarray(neighbor_band)
        neighbor_img = neighbor_img.resize((tile_band.shape[1], tile_band.shape[0]), Image.Resampling.LANCZOS)
        neighbor_band = np.asarray(neighbor_img, dtype=np.uint8)

    result[:, :overlap, :] = _match_band_to_reference(tile_band, neighbor_band)
    return result


def harmonize_top_edge(tile: np.ndarray, top_neighbor: np.ndarray, overlap_px: int) -> np.ndarray:
    """Adjust the top overlap band of tile to match the bottom edge of the top neighbor."""
    overlap = min(overlap_px, tile.shape[0], top_neighbor.shape[0])
    if overlap <= 0:
        return tile

    result = tile.copy()
    neighbor_band = top_neighbor[-overlap:, :, :]
    tile_band = tile[:overlap, :, :]
    if neighbor_band.shape != tile_band.shape:
        neighbor_img = Image.fromarray(neighbor_band)
        neighbor_img = neighbor_img.resize((tile_band.shape[1], tile_band.shape[0]), Image.Resampling.LANCZOS)
        neighbor_band = np.asarray(neighbor_img, dtype=np.uint8)

    result[:overlap, :, :] = _match_band_to_reference(tile_band, neighbor_band)
    return result


def repair_tile_seams(
    tile_path: Path,
    output_path: Path,
    overlap_px: int,
    left_neighbor_path: Path | None = None,
    top_neighbor_path: Path | None = None,
) -> Path:
    """Color-harmonize overlap edges using already-processed neighbor tiles."""
    tile = np.asarray(ensure_rgb_image(tile_path), dtype=np.uint8)

    if left_neighbor_path and left_neighbor_path.is_file():
        left = np.asarray(ensure_rgb_image(left_neighbor_path), dtype=np.uint8)
        tile = harmonize_left_edge(tile, left, overlap_px)

    if top_neighbor_path and top_neighbor_path.is_file():
        top = np.asarray(ensure_rgb_image(top_neighbor_path), dtype=np.uint8)
        tile = harmonize_top_edge(tile, top, overlap_px)

    return save_rgb_image(Image.fromarray(tile, mode="RGB"), output_path)
