"""Tests for seam harmonization."""

from pathlib import Path

import numpy as np
from PIL import Image

from app.services.image_utils import save_rgb_image
from app.services.seam_repair import harmonize_left_edge, repair_tile_seams


def test_harmonize_left_edge_shifts_mean(tmp_path: Path):
    left = np.zeros((64, 64, 3), dtype=np.uint8)
    left[:, -8:, :] = 200
    tile = np.zeros((64, 64, 3), dtype=np.uint8)
    tile[:, :8, :] = 50

    result = harmonize_left_edge(tile, left, overlap_px=8)
    assert result[:, :8, :].mean() > tile[:, :8, :].mean()


def test_repair_tile_seams_writes_output(tmp_path: Path):
    tile_path = tmp_path / "tile.png"
    left_path = tmp_path / "left.png"
    out_path = tmp_path / "out.png"

    save_rgb_image(Image.new("RGB", (32, 32), color=(100, 80, 60)), tile_path)
    save_rgb_image(Image.new("RGB", (32, 32), color=(200, 180, 160)), left_path)

    repair_tile_seams(tile_path, out_path, overlap_px=8, left_neighbor_path=left_path)
    assert out_path.is_file()
