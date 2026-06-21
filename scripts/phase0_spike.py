#!/usr/bin/env python3
"""
Phase 0 feasibility spike: one blueprint + 3x3 context-conditioned tiles.

Usage:
    python scripts/phase0_spike.py --prompt "A serene mountain lake at golden hour"
    python scripts/phase0_spike.py --dry-run

Requires XAI_API_KEY (system env or .env).
Outputs: data/runs/{run_id}/ — see doc/STORAGE_ARCHITECTURE.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings, project_root  # noqa: E402
from app.core.grid_math import (  # noqa: E402
    GridPlanRequest,
    build_grid_plan,
    closest_xai_aspect_ratio,
    spatial_context_for_tile,
    tile_key,
    wavefront_order,
)
from app.core.storage import RunPaths  # noqa: E402
from app.services.compositor_simple import stitch_all_tiles  # noqa: E402
from app.services.image_utils import (  # noqa: E402
    build_comparison_image,
    crop_blueprint_for_tile,
    save_overlap_reference,
    save_rgb_image,
)
from app.services.local_gpu import is_comfyui_available  # noqa: E402
from app.services.xai_adapter import XAIImageEngine  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("phase0_spike")

DEFAULT_STYLE_ANCHOR = (
    "Ultra-detailed digital matte painting, cohesive cinematic lighting, "
    "consistent color grading, natural atmospheric perspective."
)
DEFAULT_PROMPT = (
    "A vast alpine valley at golden hour with a winding river, pine forests, "
    "distant snow peaks, and soft clouds."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tessera Phase 0 feasibility spike")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Master scene prompt")
    parser.add_argument("--style-anchor", default=DEFAULT_STYLE_ANCHOR, help="Fixed style block")
    parser.add_argument("--rows", type=int, default=3, help="Grid rows (default: 3)")
    parser.add_argument("--cols", type=int, default=3, help="Grid cols (default: 3)")
    parser.add_argument("--run-id", default=None, help="Optional run folder name")
    parser.add_argument("--dry-run", action="store_true", help="Plan grid only; skip API calls")
    return parser.parse_args()


def build_tile_prompt(
    style_anchor: str,
    master_prompt: str,
    row: int,
    col: int,
    rows: int,
    cols: int,
) -> str:
    spatial = spatial_context_for_tile(row, col, rows, cols)
    return (
        f"{style_anchor} Scene: {master_prompt}. "
        f"This tile covers the {spatial}. "
        "<IMAGE_0> is the blueprint guide for this tile region. "
        "<IMAGE_1> is the left-edge reference. <IMAGE_2> is the top-edge reference. "
        "Continue seamlessly from the adjacent reference edges; match exact color grading, "
        "lighting, and texture at the boundary."
    )


def build_wavefront_sequence(rows: int, cols: int) -> list[tuple[int, int, int]]:
    """Return (sequence, row, col) in wavefront generation order."""
    sequence: list[tuple[int, int, int]] = []
    seq = 1
    for wave in wavefront_order(rows, cols):
        for row, col in wave:
            sequence.append((seq, row, col))
            seq += 1
    return sequence


async def run_spike(args: argparse.Namespace) -> dict:
    settings = get_settings()
    settings.ensure_dirs()

    run_id = args.run_id or datetime.now(timezone.utc).strftime("phase0_%Y%m%d_%H%M%S")
    paths = RunPaths.create(settings.runs_dir, run_id)
    paths.ensure_all()

    plan = build_grid_plan(
        GridPlanRequest(
            rows=args.rows,
            cols=args.cols,
            base_tile_px=settings.base_tile_px,
            upscale_factor=settings.local_upscale_factor,
            overlap_fraction=settings.overlap_fraction,
        )
    )

    manifest: dict = {
        "run_id": run_id,
        "prompt": args.prompt,
        "style_anchor": args.style_anchor,
        "grid_plan": plan.model_dump(),
        "dry_run": args.dry_run,
        "storage_root": paths.relative(paths.root, project_root()),
        "sequence": [],
        "outputs": {},
    }

    logger.info(
        "Grid plan: %sx%s tiles, canvas %sx%s, stride=%s, overlap=%spx",
        plan.rows,
        plan.cols,
        plan.width_px,
        plan.height_px,
        plan.stride,
        plan.overlap_px,
    )
    logger.info("Run folder: %s", paths.root)

    if args.dry_run:
        paths.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        logger.info("Dry run complete. Manifest: %s", paths.manifest_path)
        return manifest

    blueprint_path = paths.blueprint_path()
    aspect_ratio = closest_xai_aspect_ratio(plan.width_px, plan.height_px)

    async with XAIImageEngine(settings) as engine:
        logger.info("Generating blueprint (aspect_ratio=%s)...", aspect_ratio)
        await engine.generate_blueprint(
            prompt=f"{args.style_anchor} {args.prompt}",
            output_path=blueprint_path,
            aspect_ratio=aspect_ratio,
            resolution="2k",
        )
        manifest["outputs"]["blueprint"] = paths.relative(blueprint_path, paths.root)

        tile_paths: dict[str, Path] = {}
        left_ref_paths: dict[str, Path] = {}
        top_ref_paths: dict[str, Path] = {}

        for seq, row, col in build_wavefront_sequence(plan.rows, plan.cols):
            key = tile_key(row, col)
            crop_path = paths.ref_blueprint_crop_path(seq, row, col)
            crop = crop_blueprint_for_tile(blueprint_path, row, col, plan)
            save_rgb_image(crop, crop_path)

            left_ref = left_ref_paths.get(tile_key(row, col - 1)) if col > 0 else None
            top_ref = top_ref_paths.get(tile_key(row - 1, col)) if row > 0 else None

            prompt = build_tile_prompt(
                args.style_anchor,
                args.prompt,
                row,
                col,
                plan.rows,
                plan.cols,
            )
            tile_path = paths.tile_path(seq, row, col)
            logger.info("Tile %s/%s: generating %s (wavefront seq %s)", seq, plan.tile_count, key, seq)
            await engine.generate_tile(
                prompt=prompt,
                blueprint_crop_path=crop_path,
                left_neighbor_path=left_ref,
                top_neighbor_path=top_ref,
                output_path=tile_path,
                aspect_ratio="1:1",
                resolution="2k",
            )
            tile_paths[key] = tile_path

            left_strip = paths.ref_left_strip_path(seq, row, col)
            top_strip = paths.ref_top_strip_path(seq, row, col)
            save_overlap_reference(
                tile_path,
                "right",
                plan.overlap_px,
                left_strip,
                settings.placeholder_size,
            )
            save_overlap_reference(
                tile_path,
                "bottom",
                plan.overlap_px,
                top_strip,
                settings.placeholder_size,
            )
            left_ref_paths[key] = left_strip
            top_ref_paths[key] = top_strip

            manifest["sequence"].append(
                {
                    "seq": seq,
                    "coord": key,
                    "tile": paths.relative(tile_path, paths.root),
                    "refs": {
                        "blueprint_crop": paths.relative(crop_path, paths.root),
                        "left_strip": paths.relative(left_ref, paths.root) if left_ref else None,
                        "top_strip": paths.relative(top_ref, paths.root) if top_ref else None,
                    },
                }
            )

    mosaic_hard = paths.final_hard_paste_path()
    mosaic_feather = paths.final_feather_blend_path()
    stitch_all_tiles(tile_paths, plan, mosaic_hard, blend_mode="hard")
    stitch_all_tiles(tile_paths, plan, mosaic_feather, blend_mode="feather")
    manifest["outputs"]["mosaic_hard_paste"] = paths.relative(mosaic_hard, paths.root)
    manifest["outputs"]["mosaic_feather_blend"] = paths.relative(mosaic_feather, paths.root)

    comfy_available = await is_comfyui_available(settings)
    manifest["comfyui_available"] = comfy_available

    if comfy_available:
        logger.info("ComfyUI detected; full inpaint workflow arrives in Phase 1.")
    else:
        logger.info("ComfyUI not running; feather blend is the Phase 0 local baseline.")

    comparison_path = paths.final_comparison_path()
    build_comparison_image(
        mosaic_hard,
        mosaic_feather,
        comparison_path,
        labels=("hard paste (raw seams)", "feather blend (local baseline)"),
    )
    manifest["outputs"]["comparison"] = paths.relative(comparison_path, paths.root)

    paths.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    logger.info("Phase 0 complete.")
    logger.info("Hard paste mosaic: %s", mosaic_hard)
    logger.info("Feather blend mosaic: %s", mosaic_feather)
    logger.info("Manifest: %s", paths.manifest_path)
    return manifest


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(run_spike(args))
    except KeyboardInterrupt:
        logger.error("Interrupted.")
        sys.exit(130)
    except Exception as exc:
        logger.error("Phase 0 failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
