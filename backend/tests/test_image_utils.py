"""Tests for blueprint normalization and canvas-proportional crops."""

from pathlib import Path

from PIL import Image

from app.core.grid_math import GridPlanRequest, build_grid_plan
from app.services.image_utils import (
    crop_blueprint_for_tile,
    normalize_blueprint_for_plan,
    save_rgb_image,
)


def _make_plan(width: int, height: int):
    return build_grid_plan(GridPlanRequest(width_px=width, height_px=height))


def test_normalize_blueprint_to_ultrawide_canvas(tmp_path: Path):
    plan = _make_plan(8192, 2048)
    blueprint = Image.new("RGB", (2048, 922), color=(40, 40, 40))
    normalized = normalize_blueprint_for_plan(blueprint, plan)
    assert normalized.size == (2048, 512)


def test_crop_ultrawide_1x5_columns(tmp_path: Path):
    plan = build_grid_plan(GridPlanRequest(rows=1, cols=5))
    assert plan.rows == 1
    assert plan.cols == 5
    assert plan.width_px == 8192
    assert plan.height_px == 2048

    blueprint = Image.new("RGB", (2048, 512), color=(0, 0, 0))
    for x in range(1024):
        for y in range(512):
            blueprint.putpixel((x, y), (200, 0, 0))
    for x in range(1024, 2048):
        for y in range(512):
            blueprint.putpixel((x, y), (0, 0, 200))

    bp_path = tmp_path / "blueprint.png"
    save_rgb_image(blueprint, bp_path)

    left = crop_blueprint_for_tile(bp_path, 0, 0, plan)
    right = crop_blueprint_for_tile(bp_path, 0, 4, plan)
    assert left.size == (2048, 2048)
    assert left.getpixel((1024, 1024))[0] > left.getpixel((1024, 1024))[2]
    assert right.getpixel((1024, 1024))[2] > right.getpixel((1024, 1024))[0]
