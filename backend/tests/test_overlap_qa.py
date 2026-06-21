"""Tests for overlap QA."""

from pathlib import Path

import numpy as np
from PIL import Image

from app.services.image_utils import save_rgb_image
from app.services.overlap_qa import overlap_mse, score_tile_seams


def test_identical_overlap_has_zero_mse(tmp_path: Path):
    path = tmp_path / "tile.png"
    save_rgb_image(Image.new("RGB", (64, 64), color=(100, 120, 140)), path)
    mse = overlap_mse(path, path, tile_edge="left", neighbor_edge="right", overlap_px=8)
    assert mse == 0.0


def test_different_overlap_fails_qa(tmp_path: Path):
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    save_rgb_image(Image.new("RGB", (64, 64), color=(20, 20, 20)), left)
    save_rgb_image(Image.new("RGB", (64, 64), color=(240, 240, 240)), right)
    worst, ok, _ = score_tile_seams(right, 8, left_neighbor_path=left, threshold=100.0)
    assert worst > 100.0
    assert ok is False
