# Image Storage Architecture

**Project:** Tessera v3  
**Last updated:** June 2026  
**Related:** [MASTER_PLAN.md](MASTER_PLAN.md)

---

## Principles

1. **One run = one folder** — every generation job gets an isolated directory under `data/runs/`.
2. **Working vs final separation** — intermediates live in `working/`; review/export artifacts live in `final/`.
3. **Sequential filenames** — zero-padded sequence numbers reflect wavefront generation order (`001`, `002`, …).
4. **Human-readable coordinates** — tile files include grid position (`r0-c0`, `r1-c2`) for quick inspection.
5. **Manifest as index** — each run's `manifest.json` maps sequence numbers, coordinates, and relative paths.
6. **Nothing huge in git** — all generated binaries stay gitignored; only folder skeleton (`.gitkeep`) is tracked.

---

## Top-Level Layout

```text
art_ai_mosaic_r1/
└── data/
    ├── cache/                         # Shared, reusable assets (cross-run)
    │   └── placeholders/
    │       └── black_512.png          # xAI AR-lock placeholder
    └── runs/                          # One subfolder per generation job
        └── {run_id}/
            ├── manifest.json
            ├── blueprint/
            ├── working/
            └── final/
```

### Environment override

Set `DATA_DIR` in `.env` to relocate the entire tree (default: `./data` relative to project root).

---

## Per-Run Structure

```text
data/runs/{run_id}/
├── manifest.json                      # Job metadata + file index
│
├── blueprint/                         # STAGE 1 — Master composition (cloud)
│   └── 01_blueprint.png               # Single 2K blueprint; never final output
│
├── working/                           # INTERMEDIATES — safe to delete after success
│   ├── tiles/                         # STAGE 2 — Raw cloud tiles (download order)
│   │   ├── 001_tile_r0-c0.png
│   │   ├── 002_tile_r0-c1.png
│   │   ├── 003_tile_r0-c2.png
│   │   └── ...
│   ├── refs/                          # API context images sent with each tile
│   │   ├── 001_ref_blueprint_crop_r0-c0.png
│   │   ├── 001_ref_left_strip_r0-c0.png   # (only when neighbor exists)
│   │   ├── 001_ref_top_strip_r0-c0.png
│   │   └── ...
│   └── processed/                     # STAGE 3 — Post-ComfyUI tiles (Phase 1+)
│       └── (empty in Phase 0)
│
└── final/                             # DELIVERABLES — inspect, compare, export
    ├── 01_mosaic_hard_paste.png       # Raw tile paste (seams visible)
    ├── 02_mosaic_feather_blend.png    # Classical overlap blend
    └── 03_comparison_hard_vs_feather.png
```

### Run ID format

| Phase | Pattern | Example |
|-------|---------|---------|
| Phase 0 spike | `phase0_YYYYMMDD_HHMMSS` | `phase0_20260621_155420` |
| Phase 1+ jobs | `job_{id}` | `job_a3f9b2c1d4e5` |

---

## Filename Convention

```text
{seq}_{category}_{detail}_{rROW-cCOL}.png
```

| Segment | Meaning | Example |
|---------|---------|---------|
| `seq` | 3-digit wavefront order (001–999) | `007` |
| `category` | `tile`, `ref_blueprint_crop`, `ref_left_strip`, `ref_top_strip` | `tile` |
| `detail` | Optional subtype | — |
| `rROW-cCOL` | Grid coordinate | `r1-c2` |

**Final outputs** use a simpler staged prefix:

```text
01_mosaic_hard_paste.png
02_mosaic_feather_blend.png
03_comparison_hard_vs_feather.png
```

Phase 1 additions:

```text
final/04_mosaic_inpaint.png            # After ComfyUI seam repair
final/05_master.bigtiff                # Pyramidal BigTIFF delivery
```

---

## Stage → Folder Mapping

| Pipeline stage | Folder | Lifecycle |
|----------------|--------|-----------|
| Stage 0 — Grid plan | `manifest.json` only | Permanent (metadata) |
| Stage 1 — Blueprint | `blueprint/` | Keep for reproducibility |
| Stage 2 — Cloud tiles | `working/tiles/` | Working; optional purge |
| Stage 2 — Context refs | `working/refs/` | Working; optional purge |
| Stage 3 — Local GPU | `working/processed/` | Working; optional purge |
| Stage 4 — Composite | `final/` | **Keep** — primary deliverables |
| Stage 5 — Export | `final/exports/` (Phase 4) | Keep until user clears |

---

## manifest.json Schema (Phase 0)

```json
{
  "run_id": "phase0_20260621_154823",
  "prompt": "...",
  "style_anchor": "...",
  "grid_plan": { "rows": 3, "cols": 3, "...": "..." },
  "dry_run": false,
  "sequence": [
    {
      "seq": 1,
      "coord": "0,0",
      "tile": "working/tiles/001_tile_r0-c0.png",
      "refs": {
        "blueprint_crop": "working/refs/001_ref_blueprint_crop_r0-c0.png",
        "left_strip": null,
        "top_strip": null
      }
    }
  ],
  "outputs": {
    "blueprint": "blueprint/01_blueprint.png",
    "mosaic_hard_paste": "final/01_mosaic_hard_paste.png",
    "mosaic_feather_blend": "final/02_mosaic_feather_blend.png",
    "comparison": "final/03_comparison_hard_vs_feather.png"
  },
  "comfyui_available": false
}
```

All paths in the manifest are **relative to the run root** for portability.

---

## Cache Directory

```text
data/cache/
└── placeholders/
    └── black_512.png                  # Solid black 512×512 for xAI ≥2-image rule
```

Shared across all runs. Created once on first API call.

---

## Git Policy

| Path | Git |
|------|-----|
| `data/runs/.gitkeep` | Tracked |
| `data/cache/.gitkeep` | Tracked |
| `data/runs/**` (generated) | **Ignored** |
| `data/cache/placeholders/*.png` | **Ignored** |

Legacy paths (`tiles/`, `output/`) are also gitignored for backward compatibility.

---

## Python API

```python
from app.core.config import get_settings
from app.core.storage import RunPaths

settings = get_settings()
paths = RunPaths.create(settings.runs_dir, "phase0_20260621_154823")
paths.ensure_all()

blueprint = paths.blueprint_path()           # blueprint/01_blueprint.png
tile = paths.tile_path(1, 0, 0)              # working/tiles/001_tile_r0-c0.png
final = paths.final_feather_blend_path()     # final/02_mosaic_feather_blend.png
```

---

## Future Extensions (Phase 1+)

```text
data/runs/{run_id}/
├── working/
│   └── canvas.dat                     # memmap scratch (Stage 4)
├── final/
│   ├── exports/                       # Export Bay zip contents
│   │   ├── 1080p.jpg
│   │   └── 4k.png
│   └── 05_master.bigtiff
└── state/
    └── tiles.sqlite                   # Resumable job state (Phase 3)
```

---

## Cleanup Guidelines

| Scenario | Action |
|----------|--------|
| Successful run, disk tight | Delete `working/` subfolder; keep `blueprint/` + `final/` + manifest |
| Failed mid-run | Keep entire run folder for debugging |
| Re-run same prompt | New `run_id` folder; never overwrite prior runs |
