"""Tests for overlap blending."""

import numpy as np

from app.services.blend_utils import merge_tile_into_canvas


def test_first_tile_writes_full_region():
    canvas = np.zeros((100, 100, 3), dtype=np.uint8)
    tile = np.full((20, 20, 3), 200, dtype=np.uint8)
    merge_tile_into_canvas(canvas, tile, 0, 0, overlap_px=5, row=0, col=0)
    assert canvas[0, 0, 0] == 200
    assert canvas[19, 19, 0] == 200


def test_second_column_blends_overlap():
    canvas = np.zeros((50, 50, 3), dtype=np.uint8)
    left = np.full((20, 20, 3), 100, dtype=np.uint8)
    right = np.full((20, 20, 3), 200, dtype=np.uint8)
    merge_tile_into_canvas(canvas, left, 0, 0, overlap_px=5, row=0, col=0)
    merge_tile_into_canvas(canvas, right, 15, 0, overlap_px=5, row=0, col=1)
    # Overlap band should be between 100 and 200
    mid = canvas[0, 17, 0]
    assert 100 < mid < 200
