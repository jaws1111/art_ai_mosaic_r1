"""Grid planning: canvas dimensions, tile counts, dependency graph, wavefront order."""

from __future__ import annotations

import math
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

TileCoord = tuple[int, int]
AspectLabel = Literal[
    "1:1",
    "16:9",
    "9:16",
    "4:3",
    "3:4",
    "3:2",
    "2:3",
    "2:1",
    "1:2",
    "19.5:9",
    "9:19.5",
    "20:9",
    "9:20",
    "auto",
    "custom",
]

# xAI 2K blueprint / tile native size
BLUEPRINT_NATIVE_PX = 2048

# Below this long-edge, mosaic stitching adds no meaningful quality vs one image
MOSAIC_MIN_LONG_EDGE = 1536

# Below this long-edge, skip tile API entirely — resize blueprint only
BLUEPRINT_DIRECT_MAX_LONG_EDGE = 768

# Minimum tile count before mosaic mode is preferred over single-enhanced
MOSAIC_MIN_TILE_COUNT = 4

# Linear 1×N / N×1 strips: cloud tiles tend to re-scale the full scene per tile
LINEAR_GRID_MAX_CLOUD_TILES = 8

XAI_ASPECT_RATIOS: tuple[str, ...] = (
    "1:1",
    "16:9",
    "9:16",
    "4:3",
    "3:4",
    "3:2",
    "2:3",
    "2:1",
    "1:2",
    "19.5:9",
    "9:19.5",
    "20:9",
    "9:20",
    "auto",
)


class CanvasFormat(BaseModel):
    mode: Literal["standard", "panorama_h", "panorama_v", "spherical"] = "standard"
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    aspect_label: AspectLabel = "custom"
    wraparound: bool = False


class GenerationMode(str, Enum):
    """How to produce the final canvas."""

    MOSAIC = "mosaic"
    SINGLE_ENHANCED = "single_enhanced"
    BLUEPRINT_DIRECT = "blueprint_direct"


class GridPlan(BaseModel):
    rows: int
    cols: int
    base_tile_px: int
    upscale_factor: int
    tile_effective: int
    overlap_fraction: float
    overlap_px: int
    stride: int
    width_px: int
    height_px: int
    dependency_graph: dict[str, list[str]]
    wrap_horizontal: bool = False
    wrap_vertical: bool = False
    generation_mode: GenerationMode = GenerationMode.MOSAIC
    strategy_message: str = ""
    local_upscale_factor: int = 1
    use_mosaic_stitch: bool = True

    @property
    def tile_count(self) -> int:
        return self.rows * self.cols

    @property
    def long_edge(self) -> int:
        return max(self.width_px, self.height_px)


def tile_key(row: int, col: int) -> str:
    return f"{row},{col}"


def parse_tile_key(key: str) -> TileCoord:
    row_str, col_str = key.split(",")
    return int(row_str), int(col_str)


def compute_tile_effective(base_tile_px: int, upscale_factor: int) -> int:
    return base_tile_px * upscale_factor


def compute_stride(tile_effective: int, overlap_fraction: float) -> int:
    return max(1, int(tile_effective * (1 - overlap_fraction)))


def compute_grid_dimensions(
    width_px: int,
    height_px: int,
    tile_effective: int,
    overlap_fraction: float,
) -> tuple[int, int, int]:
    """Return rows, cols, stride for a target canvas size."""
    stride = compute_stride(tile_effective, overlap_fraction)
    cols = max(1, math.ceil((width_px - tile_effective) / stride) + 1)
    rows = max(1, math.ceil((height_px - tile_effective) / stride) + 1)
    return rows, cols, stride


def canvas_size_for_grid(
    rows: int,
    cols: int,
    tile_effective: int,
    stride: int,
) -> tuple[int, int]:
    width_px = (cols - 1) * stride + tile_effective
    height_px = (rows - 1) * stride + tile_effective
    return width_px, height_px


def wrap_flags_for_canvas(mode: str, wraparound: bool = False) -> tuple[bool, bool]:
    """Phase 2b: derive seam wrap from canvas mode."""
    if mode == "panorama_h":
        return True, False
    if mode == "panorama_v":
        return False, True
    if mode == "spherical":
        return True, True
    if wraparound:
        return True, False
    return False, False


def build_dependency_graph(
    rows: int,
    cols: int,
    *,
    wrap_horizontal: bool = False,
    wrap_vertical: bool = False,
) -> dict[str, list[str]]:
    graph: dict[str, list[str]] = {}
    for row in range(rows):
        for col in range(cols):
            deps: list[str] = []
            if col > 0:
                deps.append(tile_key(row, col - 1))
            elif wrap_horizontal and cols > 1:
                deps.append(tile_key(row, cols - 1))
            if row > 0:
                deps.append(tile_key(row - 1, col))
            elif wrap_vertical and rows > 1:
                deps.append(tile_key(rows - 1, col))
            graph[tile_key(row, col)] = deps
    return graph


def closing_pass_tiles(
    rows: int,
    cols: int,
    *,
    wrap_horizontal: bool = False,
    wrap_vertical: bool = False,
) -> list[TileCoord]:
    """Tiles needing a post-grid seam pass to close wraparound loops."""
    coords: list[TileCoord] = []
    seen: set[TileCoord] = set()
    if wrap_horizontal:
        for row in range(rows):
            coord = (row, 0)
            if coord not in seen:
                coords.append(coord)
                seen.add(coord)
    if wrap_vertical:
        for col in range(cols):
            coord = (0, col)
            if coord not in seen:
                coords.append(coord)
                seen.add(coord)
    return coords


def wavefront_order(rows: int, cols: int) -> list[list[TileCoord]]:
    """Anti-diagonal groups; tiles in each group can run concurrently."""
    max_sum = (rows - 1) + (cols - 1)
    waves: list[list[TileCoord]] = []
    for total in range(max_sum + 1):
        wave: list[TileCoord] = []
        for row in range(rows):
            col = total - row
            if 0 <= col < cols:
                wave.append((row, col))
        if wave:
            waves.append(wave)
    return waves


def closest_xai_aspect_ratio(width_px: int, height_px: int) -> str:
    if height_px <= 0:
        return "1:1"
    target = width_px / height_px
    best_ratio = "1:1"
    best_delta = float("inf")
    for label in XAI_ASPECT_RATIOS:
        if label == "auto":
            continue
        num_str, den_str = label.split(":")
        ratio = float(num_str) / float(den_str)
        delta = abs(ratio - target)
        if delta < best_delta:
            best_delta = delta
            best_ratio = label
    return best_ratio


class GridPlanRequest(BaseModel):
    width_px: int | None = None
    height_px: int | None = None
    rows: int | None = None
    cols: int | None = None
    base_tile_px: int = 2048
    upscale_factor: int = Field(default=1, ge=1)
    overlap_fraction: float = Field(default=0.25, gt=0.0, lt=1.0)
    wrap_horizontal: bool = False
    wrap_vertical: bool = False

    @model_validator(mode="after")
    def validate_sizing_mode(self) -> GridPlanRequest:
        has_canvas = self.width_px is not None and self.height_px is not None
        has_grid = self.rows is not None and self.cols is not None
        if has_canvas == has_grid:
            raise ValueError("Provide either width_px+height_px or rows+cols, not both.")
        return self


def resolve_generation_strategy(
    width_px: int,
    height_px: int,
    base_tile_px: int,
    upscale_factor: int,
    overlap_fraction: float,
) -> tuple[GenerationMode, int, int, int, str, int, bool]:
    """
    Choose mosaic vs single-tile vs blueprint-only.

    Returns: mode, rows, cols, local_upscale_factor, message, adjusted_cloud_upscale, use_stitch
    """
    long_edge = max(width_px, height_px)
    naive_rows, naive_cols, _ = compute_grid_dimensions(
        width_px, height_px, base_tile_px * upscale_factor, overlap_fraction
    )
    naive_count = naive_rows * naive_cols

    if long_edge <= BLUEPRINT_DIRECT_MAX_LONG_EDGE:
        return (
            GenerationMode.BLUEPRINT_DIRECT,
            1,
            1,
            1,
            f"Canvas {width_px}×{height_px} is below {BLUEPRINT_DIRECT_MAX_LONG_EDGE}px — "
            "using blueprint resize only (mosaic would not improve quality).",
            1,
            False,
        )

    if naive_count == 1 and long_edge <= base_tile_px:
        return (
            GenerationMode.SINGLE_ENHANCED,
            1,
            1,
            1,
            f"Canvas fits in one {base_tile_px}px cloud tile — single generation + "
            f"downscale to {width_px}×{height_px} (no mosaic grid).",
            1,
            False,
        )

    if naive_count == 1 and long_edge > base_tile_px:
        local_up = min(4, max(1, math.ceil(long_edge / base_tile_px)))
        return (
            GenerationMode.SINGLE_ENHANCED,
            1,
            1,
            local_up,
            f"Single {base_tile_px}px tile + local {local_up}× enhance to {width_px}×{height_px} "
            "(mosaic grid not needed).",
            1,
            False,
        )

    if naive_count < MOSAIC_MIN_TILE_COUNT or long_edge < MOSAIC_MIN_LONG_EDGE:
        local_up = min(4, max(1, upscale_factor, math.ceil(long_edge / base_tile_px)))
        return (
            GenerationMode.SINGLE_ENHANCED,
            1,
            1,
            local_up,
            f"Only {naive_count} tile(s) would be used — switching to single enhanced path "
            f"with local {local_up}× (mosaic benefit negligible below {MOSAIC_MIN_LONG_EDGE}px).",
            1,
            False,
        )

    if (naive_rows == 1 or naive_cols == 1) and naive_count <= LINEAR_GRID_MAX_CLOUD_TILES:
        local_up = min(4, max(1, math.ceil(long_edge / base_tile_px)))
        orient = f"{naive_cols}×1" if naive_rows == 1 else f"1×{naive_rows}"
        return (
            GenerationMode.SINGLE_ENHANCED,
            1,
            1,
            local_up,
            f"Linear strip ({orient}, {naive_count} tiles) → blueprint + local {local_up}× upscale "
            "(cloud strip tiles misalign on ultrawide canvases).",
            1,
            False,
        )

    return (
        GenerationMode.MOSAIC,
        naive_rows,
        naive_cols,
        upscale_factor,
        f"Full mosaic: {naive_rows}×{naive_cols} grid ({naive_count} cloud tiles) + "
        f"{upscale_factor}× local upscale per tile.",
        upscale_factor,
        True,
    )


def build_grid_plan(request: GridPlanRequest) -> GridPlan:
    if request.rows is not None and request.cols is not None:
        tile_effective = compute_tile_effective(request.base_tile_px, request.upscale_factor)
        stride = compute_stride(tile_effective, request.overlap_fraction)
        width_px, height_px = canvas_size_for_grid(
            request.rows, request.cols, tile_effective, stride
        )
        mode = GenerationMode.MOSAIC
        msg = f"Explicit {request.rows}×{request.cols} grid."
        local_up = request.upscale_factor
        use_stitch = True
        rows, cols = request.rows, request.cols
        cloud_upscale = request.upscale_factor
    else:
        assert request.width_px is not None and request.height_px is not None
        width_px, height_px = request.width_px, request.height_px
        mode, rows, cols, local_up, msg, cloud_upscale, use_stitch = resolve_generation_strategy(
            width_px,
            height_px,
            request.base_tile_px,
            request.upscale_factor,
            request.overlap_fraction,
        )

    tile_effective = compute_tile_effective(request.base_tile_px, cloud_upscale)
    overlap_px = int(tile_effective * request.overlap_fraction)
    stride = compute_stride(tile_effective, request.overlap_fraction)
    dependency_graph = build_dependency_graph(
        rows,
        cols,
        wrap_horizontal=request.wrap_horizontal,
        wrap_vertical=request.wrap_vertical,
    )

    return GridPlan(
        rows=rows,
        cols=cols,
        base_tile_px=request.base_tile_px,
        upscale_factor=cloud_upscale,
        tile_effective=tile_effective,
        overlap_fraction=request.overlap_fraction,
        overlap_px=overlap_px,
        stride=stride,
        width_px=width_px,
        height_px=height_px,
        dependency_graph=dependency_graph,
        wrap_horizontal=request.wrap_horizontal,
        wrap_vertical=request.wrap_vertical,
        generation_mode=mode,
        strategy_message=msg,
        local_upscale_factor=local_up,
        use_mosaic_stitch=use_stitch,
    )


def spatial_context_for_tile(row: int, col: int, rows: int, cols: int) -> str:
    vertical = "center"
    if row == 0:
        vertical = "top"
    elif row == rows - 1:
        vertical = "bottom"

    horizontal = "center"
    if col == 0:
        horizontal = "left"
    elif col == cols - 1:
        horizontal = "right"

    if vertical == "center" and horizontal == "center":
        return "center of the scene"
    return f"{vertical} {horizontal} region of the scene"
