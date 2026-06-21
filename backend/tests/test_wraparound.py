"""Tests for panorama wraparound (Phase 2b)."""

from app.core.grid_math import (
    build_dependency_graph,
    closing_pass_tiles,
    wrap_flags_for_canvas,
)


def test_panorama_h_wrap_flag():
    wrap_h, wrap_v = wrap_flags_for_canvas("panorama_h")
    assert wrap_h is True
    assert wrap_v is False


def test_wrap_dependency_links_first_column_to_last():
    graph = build_dependency_graph(3, 4, wrap_horizontal=True)
    assert "0,3" in graph["0,0"]


def test_closing_pass_includes_wrap_edges():
    coords = closing_pass_tiles(3, 4, wrap_horizontal=True, wrap_vertical=False)
    assert (0, 0) in coords
    assert (1, 0) in coords
    assert (2, 0) in coords
    assert all(c[1] == 0 for c in coords)
