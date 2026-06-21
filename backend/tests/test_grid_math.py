"""Tests for grid planning math."""

from app.core.grid_math import (
    GenerationMode,
    GridPlanRequest,
    build_grid_plan,
    build_dependency_graph,
    closest_xai_aspect_ratio,
    resolve_generation_strategy,
    wavefront_order,
)


def test_phase0_grid_is_3x3():
    plan = build_grid_plan(GridPlanRequest(rows=3, cols=3))
    assert plan.rows == 3
    assert plan.cols == 3
    assert plan.tile_count == 9
    assert plan.width_px == 5120
    assert plan.height_px == 5120


def test_dependency_graph_corner_tile():
    graph = build_dependency_graph(3, 3)
    assert graph["0,0"] == []
    assert graph["0,1"] == ["0,0"]
    assert graph["1,1"] == ["1,0", "0,1"]


def test_wavefront_has_three_groups_for_first_row():
    waves = wavefront_order(3, 3)
    assert waves[0] == [(0, 0)]
    assert (0, 1) in waves[1]
    assert (1, 0) in waves[1]


def test_closest_aspect_ratio_square():
    assert closest_xai_aspect_ratio(5120, 5120) == "1:1"


def test_canvas_sizing_from_pixels():
    plan = build_grid_plan(
        GridPlanRequest(width_px=10000, height_px=10000, upscale_factor=2)
    )
    assert plan.tile_effective == 4096
    assert plan.rows >= 3
    assert plan.cols >= 3


def test_blueprint_direct_for_tiny_canvas():
    plan = build_grid_plan(GridPlanRequest(width_px=512, height_px=512))
    assert plan.generation_mode == GenerationMode.BLUEPRINT_DIRECT
    assert plan.tile_count == 1
    assert plan.use_mosaic_stitch is False


def test_single_enhanced_when_few_tiles():
    mode, rows, cols, local_up, _, _, use_stitch = resolve_generation_strategy(
        1200, 1200, 2048, 1, 0.25
    )
    assert mode == GenerationMode.SINGLE_ENHANCED
    assert rows == cols == 1
    assert use_stitch is False


def test_mosaic_for_large_canvas():
    plan = build_grid_plan(GridPlanRequest(width_px=5120, height_px=5120))
    assert plan.generation_mode == GenerationMode.MOSAIC
    assert plan.tile_count >= 4
    assert plan.use_mosaic_stitch is True


def test_panorama_8k_uses_blueprint_upscale_not_strip_mosaic():
    plan = build_grid_plan(GridPlanRequest(width_px=8192, height_px=2048))
    assert plan.generation_mode == GenerationMode.SINGLE_ENHANCED
    assert plan.rows == plan.cols == 1
    assert plan.use_mosaic_stitch is False
    assert plan.local_upscale_factor == 4
