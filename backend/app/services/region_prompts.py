"""Per-tile and blueprint prompt resolution for regional mosaics (Phase 2a)."""

from __future__ import annotations

from app.models.regions import PromptRegion


def _intersection_area(
    ax: float, ay: float, aw: float, ah: float,
    bx: float, by: float, bw: float, bh: float,
) -> float:
    ix0 = max(ax, bx)
    iy0 = max(ay, by)
    ix1 = min(ax + aw, bx + bw)
    iy1 = min(ay + ah, by + bh)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    return (ix1 - ix0) * (iy1 - iy0)


def tile_normalized_bounds(row: int, col: int, rows: int, cols: int) -> tuple[float, float, float, float]:
    """Return x, y, w, h in 0–1 canvas space for a grid cell."""
    return col / cols, row / rows, 1.0 / cols, 1.0 / rows


def region_coverages(
    row: int,
    col: int,
    rows: int,
    cols: int,
    regions: list[PromptRegion],
) -> list[tuple[PromptRegion, float]]:
    tx, ty, tw, th = tile_normalized_bounds(row, col, rows, cols)
    tile_area = tw * th
    scored: list[tuple[PromptRegion, float]] = []
    for region in regions:
        area = _intersection_area(tx, ty, tw, th, region.x, region.y, region.w, region.h)
        if area > 0:
            scored.append((region, area / tile_area))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


def resolve_tile_content(
    master_prompt: str,
    regions: list[PromptRegion],
    row: int,
    col: int,
    rows: int,
    cols: int,
) -> str:
    """Blend regional prompts for a tile; falls back to master when no regions overlap."""
    if not regions:
        return master_prompt

    coverages = region_coverages(row, col, rows, cols, regions)
    if not coverages:
        return master_prompt

    if len(coverages) == 1 or coverages[0][1] >= 0.85:
        return coverages[0][0].prompt

    parts = [f"{region.prompt} (~{int(frac * 100)}% of tile)" for region, frac in coverages[:3]]
    transition = "; ".join(parts)
    return (
        f"Transition scene blending: {transition}. "
        "Smoothly merge these adjacent zones within this tile — "
        "consistent lighting and natural continuity at boundaries."
    )


def build_blueprint_prompt(
    style_anchor: str,
    master_prompt: str,
    regions: list[PromptRegion],
) -> str:
    if not regions:
        return f"{style_anchor} {master_prompt}"

    zone_lines = []
    for region in regions:
        label = region.label or region.id
        zone_lines.append(
            f"- {label} (left {int(region.x * 100)}%, top {int(region.y * 100)}%, "
            f"size {int(region.w * 100)}%×{int(region.h * 100)}%): {region.prompt}"
        )
    zones = "\n".join(zone_lines)
    return (
        f"{style_anchor} Master scene layout with distinct zones:\n{zones}\n"
        f"Overall cohesion: {master_prompt}. "
        "Each zone should be visually distinct yet harmonized in lighting and palette."
    )


def build_regional_tile_prompt(
    style_anchor: str,
    master_prompt: str,
    regions: list[PromptRegion],
    row: int,
    col: int,
    rows: int,
    cols: int,
    spatial: str,
) -> str:
    content = resolve_tile_content(master_prompt, regions, row, col, rows, cols)
    return (
        f"{style_anchor} Scene: {content}. "
        f"This tile covers the {spatial}. "
        "<IMAGE_0> is the blueprint guide for this tile region. "
        "<IMAGE_1> is the left-edge reference. <IMAGE_2> is the top-edge reference. "
        "Continue seamlessly from the adjacent reference edges; match exact color grading, "
        "lighting, and texture at the boundary."
    )
