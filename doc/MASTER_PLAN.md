# Tessera v3 — Master Plan

**Project:** Multi-Megapixel Mosaic Image Engine  
**Codename:** Tessera  
**Platform:** Windows 10, RTX 4080 (16GB VRAM)  
**Last updated:** June 2026  
**Sources:** `doc/mosaic-image-engine-plan.md`, `doc/mosaic-image-engine-plan2_complete.md`

---

## Executive Summary

Tessera generates single coherent images at **>10,000×10,000px** (arbitrary aspect ratio) by orchestrating many xAI `grok-imagine-image-quality` generations into a seamless master composite. The cloud API provides creative content; the local RTX 4080 handles resolution stretching, seam repair, and compositing.

**Core division of labor:**
- **xAI** → *what* is in the picture (blueprint + tiled `/edits` calls)
- **RTX 4080** → *how big* and *how seamless* (upscale, inpaint, blend, export)

---

## 1. Load-Bearing API Constraints (xAI)

These are non-negotiable architectural rules — design around them from day one.

| Constraint | Rule |
|------------|------|
| Max resolution | Only `1k` (1024px) and `2k` (2048px). Mosaic tiling is mandatory. |
| Aspect ratio | Fixed enum per tile call. Final canvas is user-defined; tiles default to `1:1`. |
| Endpoints | `/v1/images/generations` once (blueprint); `/v1/images/edits` for all tiles. |
| Multi-image context | Max **3** source images per `/edits` call. |
| AR lock bug | **Never pass 1 image** to `/edits` — output AR locks to input. Always pass ≥2 (use black placeholder for missing neighbors). |
| No mask/inpainting | Cloud cannot guarantee perfect seams → local RTX inpainting is required. |
| No seed | Consistency via context chaining + style anchor, not determinism. |
| Temp URLs | Download/persist every tile immediately. |
| Rate limits | Wavefront scheduler + exponential backoff on `429`. |
| Batch `n` param | Variations only — not for distinct tiles. |

**Pricing reference:** ~$0.02/image + $0.002/context image. Cost is not the bottleneck; time, rate limits, and seam quality are.

---

## 2. System Architecture

### 2.1 Five-Stage Pipeline

```
User Prompt + Canvas Format
        │
        ▼
┌─────────────────────┐
│ Stage 0: Grid Math   │  rows×cols, overlap, dependency graph
└─────────────────────┘
        │
        ▼
┌──────────────────────────┐
│ Stage 1: Master Blueprint │  ONE /generations call at 2K
└──────────────────────────┘
        │
        ▼
┌────────────────────────────────┐
│ Stage 2: Cloud Tile Generation  │  /edits, wavefront-scheduled
└────────────────────────────────┘
        │
        ▼
┌────────────────────────────────┐
│ Stage 3: Local RTX Refinery     │  ComfyUI: upscale + seam inpaint
└────────────────────────────────┘
        │
        ▼
┌──────────────────────────┐
│ Stage 4: Streaming Composite│  memmap + PyTorch CUDA blend → BigTIFF
└──────────────────────────┘
        │
        ▼
┌──────────────────────────┐
│ Stage 5: Delivery         │  OpenSeadragon + Export Bay
└──────────────────────────┘
```

### 2.2 Grid Math (Stage 0)

```
base_tile_px = 2048
local_upscale_factor = 2  (default, tunable)
tile_effective = base_tile_px × local_upscale_factor  → 4096
overlap = 0.25
stride = tile_effective × (1 - overlap)
cols = ceil((width_px - tile_effective) / stride) + 1
rows = ceil((height_px - tile_effective) / stride) + 1
```

**Dependency graph:** tile `(r,c)` depends on `(r,c-1)` and `(r-1,c)`. Anti-diagonal tiles are independent → wavefront parallel scheduling.

### 2.3 Cloud Tile Generation (Stage 2)

For each tile `(r,c)`, call `/v1/images/edits` with:

1. **Prompt:** style anchor + spatial context + seam directive
2. **Image 1:** Blueprint crop for `(r,c)`
3. **Image 2:** Left neighbor overlap strip (or black 512×512 placeholder)
4. **Image 3:** Top neighbor overlap strip (or black 512×512 placeholder)
5. **aspect_ratio:** `"1:1"` (valid because ≥2 images always supplied)

### 2.4 Local RTX Pipeline (Stage 3)

ComfyUI headless API at `localhost:8188`:

| Step | Tool | Purpose |
|------|------|---------|
| Upscale | Real-ESRGAN / 4x-UltraSharp | 2048 → 4096 (2× default) |
| Seam inpaint | SDXL/FLUX + ControlNet Tile | Masked fill on overlap bands |
| Color match | PyTorch CUDA tensors | Histogram/transfer in overlap zones |

**Interface abstraction:**

```
TileGenerator (interface)
 ├── CloudGenerator   → xAI API (creative content)
 └── LocalGenerator   → ComfyUI HTTP API (upscale, inpaint, color-match)
```

### 2.5 Streaming Composite (Stage 4)

**Critical:** Do NOT use `PIL.Image.new()` for full canvas — will OOM on Windows.

- `numpy.memmap` disk-backed RGB array (`canvas.dat`)
- PyTorch CUDA for linear gradient feathering in overlap zones
- `tifffile` → pyramidal BigTIFF (streaming, low RAM)

### 2.6 Banned Dependencies

Explicitly avoid Linux-only/WSL libraries: `pyvips`, `libvips`, `gdal`.

---

## 3. Canvas & Aspect Ratio System

### Phase 1 — Standard Formats

| Mode | Description |
|------|-------------|
| Custom W×H | Any pixel dimensions (e.g. 14,000 × 6,000) |
| Presets | 16:9, 9:16, 1:1, 32:9, 4:3, 3:2, 2:1 |
| Long-edge control | Slider for 10K / 12K / 16K / 20K long edge |

```python
CanvasFormat {
  mode: "standard" | "panorama_h" | "panorama_v" | "spherical"  # latter 3 = Phase 2
  width_px: int
  height_px: int
  aspect_label: str
  wraparound: bool
}
```

### Phase 2 — 360° Formats

| Format | Approach |
|--------|----------|
| Horizontal/vertical pano | Wraparound dependency edge + closing pass |
| Spherical (equirectangular) | **Do NOT tile equirectangular directly.** Generate 6 cubemap faces via Phase 1 pipeline, reproject with `grid_sample` / `cv2.remap` |

---

## 4. UX/UI Architecture

### 4.1 Blueprint Studio (Pre-tile)

Segmented control: **[AI Generate] | [Upload Image]**

**Path A — AI Generate:**
- Master prompt textarea
- 1–3 style reference images (drag-drop)
- xAI enum AR dropdown (tooltip: defines blueprint shape, not final canvas)
- "Generate Blueprint" → 2K preview

**Path B — Upload:**
- Drop high-res image; system auto-selects closest xAI enum AR

**Gate:** "Lock Blueprint & Configure Canvas" → transitions to canvas config.

### 4.2 Mosaic Mission Control (During generation)

| Component | Function |
|-----------|----------|
| OpenSeadragon viewport | Deep-zoom; loads tiles as BigTIFF grows |
| Grid overlay toggle | Tile boundaries + overlap zones |
| Tile Status Matrix (mini-map) | WebSocket-driven grid: Queued / Cloud / Local GPU / Composited / Error |
| Metrics HUD | Elapsed, ETA, stage, API calls, est. cost, GPU load |

**Tile status colors:**
- Dark gray — Queued
- Pulsing blue — xAI generating
- Yellow — Queued for local GPU
- Orange — Upscaling / inpainting
- Green — Composited
- Red — Error (click → retry)

### 4.3 Export Bay

Modal with format × size matrix:
- **Formats:** JPEG (quality slider), PNG, WebP, Master BigTIFF
- **Sizes:** Original, 8K, 4K, 1440p, 1080p, Custom WxH
- Backend: load memmap → PyTorch `interpolate(bicubic)` on GPU → zip stream

---

## 5. Consistency Strategy

| Mechanism | Stage |
|-----------|-------|
| Style anchor string (verbatim in every prompt) | Cloud + local |
| Blueprint crop conditioning | Cloud tiles |
| Neighbor overlap conditioning | Cloud tiles |
| Local seam inpainting (ControlNet Tile) | Local |
| Color harmonization (PyTorch CUDA) | Local |
| Optional IP-Adapter style lock | Local |
| Retry-on-drift (overlap similarity check) | Phase 3 |

---

## 6. Technology Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.10+, FastAPI, Uvicorn |
| Scheduling | asyncio + semaphores (wavefront) |
| State | SQLite (`aiosqlite`) — resumable jobs |
| Local GPU | ComfyUI Windows portable, headless |
| GPU math | PyTorch CUDA 12.x |
| Image I/O | OpenCV, Pillow, NumPy |
| Large canvas | tifffile + numpy.memmap |
| Frontend | React, Tailwind CSS, OpenSeadragon |
| Real-time | WebSocket `/ws/progress` |

---

## 7. Worked Examples (Hybrid 2× Upscale)

`base_tile_px = 2048`, `overlap = 25%`

| Target Canvas | Pure-Cloud Grid | Pure-Cloud Tiles | Hybrid Grid | Hybrid Tiles | Est. Cost |
|---------------|-----------------|------------------|-------------|--------------|-----------|
| 10,000×10,000 | 7×7 | 49 | 4×4 | 16 | ~$0.42 |
| 12,000×8,000 | 8×5 | 40 | 5×3 | 15 | ~$0.39 |
| 21,300×6,000 (32:9) | 14×4 | 56 | 8×2 | 16 | ~$0.42 |
| 16,000×9,000 | 10×5 | 50 | 6×3 | 18 | ~$0.47 |

Hybrid approach ~3× reduces cloud calls while enabling local inpainting.

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Cloud seam quality unknown | Phase 0 spike; local inpaint as designed fix |
| No seed / no reproducibility | Accept variance; retry-on-drift |
| Moderation rejections mid-grid | Per-tile retry/reprompt, not job abort |
| Single-image AR lock | Always ≥2 context images + black placeholder |
| URL expiry | Immediate persist on every tile |
| Rate limit headroom unknown | Confirm with xAI; conservative wavefront concurrency |
| VRAM contention (ComfyUI + orchestrator) | Queue depth limits; monitor VRAM |
| Upscale vs content granularity tradeoff | Default 2×; expose in UI with clear tooltip |
| Pole distortion (360° spherical) | Cubemap approach, not direct equirect tiling |

---

## 9. Phased Delivery Roadmap

### Phase 0 — Feasibility Spike (Days)

**Goal:** Validate cloud tiling + local repair delta before full build.

- [ ] One blueprint via `/generations`
- [ ] 3×3 grid via `/edits` with context conditioning
- [ ] Run seams through ComfyUI inpaint pass
- [ ] Compare raw cloud seams vs locally repaired seams
- [ ] Document findings; adjust Stage 3 scope

**Deliverable:** Standalone Python script + visual comparison artifact.

---

### Phase 1 — Core Pipeline (Weeks 1–6)

**Goal:** End-to-end mosaic for standard formats, single global prompt.

#### Milestone 1.1 — Foundation (Week 1)
- [ ] Project scaffold: `backend/`, `frontend/`, `scripts/`
- [ ] `grid_math.py` — CanvasFormat model, rows/cols/stride, dependency graph
- [ ] `.env` config, logging, directory structure

#### Milestone 1.2 — xAI Adapter (Week 2)
- [ ] `XAIImageEngine` — `generate_blueprint()`, `generate_tile()`
- [ ] Strict 3-image rule with black placeholder
- [ ] Exponential backoff on 429
- [ ] Immediate tile persistence to `/tiles`

#### Milestone 1.3 — Wavefront Scheduler (Week 3)
- [ ] `mosaic_router.py` — anti-diagonal concurrent execution
- [ ] SQLite tile state tracking
- [ ] WebSocket `/ws/progress` broadcast

#### Milestone 1.4 — Local GPU Integration (Week 4)
- [ ] ComfyUI subprocess management + health check
- [ ] `LocalRTX4080Service` — upscale + inpaint workflows (exported JSON)
- [ ] Queue tiles from Stage 2 → Stage 3

#### Milestone 1.5 — Compositor (Week 5)
- [ ] `CanvasCompositor` — memmap canvas, PyTorch CUDA blend
- [ ] Pyramidal BigTIFF output via tifffile

#### Milestone 1.6 — Frontend MVP (Week 6)
- [ ] Blueprint Studio (AI generate + upload + lock)
- [ ] Canvas format selector (presets + custom W×H + long-edge)
- [ ] Mission Control (OpenSeadragon + tile matrix + metrics HUD)
- [ ] Single global prompt only

**Phase 1 exit criteria:** Generate a 10,000×10,000 mosaic from one prompt, view in OpenSeadragon, inspect seams.

---

### Phase 2 — Advanced Features (Weeks 7–12)

Two parallel tracks:

#### Track 2a — Regional Prompt Mosaic
- [ ] Layout canvas — paint regions with sub-prompts
- [ ] Region-aware blueprint generation
- [ ] Per-tile prompt blending for straddling regions
- [ ] Transition directives ("from X on left to Y on right")

#### Track 2b — 360° Formats
- [ ] Horizontal/vertical wraparound dependency graph
- [ ] Closing pass for loop edges
- [ ] Cubemap face generation (6 faces)
- [ ] Equirectangular reprojection on GPU

---

### Phase 3 — Scale & Resilience (Weeks 13–16)

- [ ] Resumable jobs (crash/429 recovery)
- [ ] Retry/backoff hardening
- [ ] 20,000px+ canvas support
- [ ] Automated overlap-similarity QA
- [ ] Auto-regeneration of drifted tiles

---

### Phase 4 — Polish (Weeks 17–20)

- [ ] Export Bay (multi-format GPU downscale)
- [ ] Style presets library
- [ ] Cost/time estimator (pre-commit)
- [ ] Job history
- [ ] Upscale factor tuning UI
- [ ] Error recovery UX (retry tile, retry stage)

---

## 10. Implementation Sequence (Cursor Directives)

Build in this exact order to prevent integration failures:

| Step | Module | Key Requirements |
|------|--------|------------------|
| 1 | `grid_math.py` | CanvasFormat, rows/cols/stride, dependency dict |
| 2 | `xai_adapter.py` | Blueprint + tile methods, 3-image rule, 429 backoff |
| 3 | `mosaic_router.py` | Wavefront scheduler, WebSocket progress |
| 4 | `local_gpu.py` | ComfyUI HTTP client, upscale + inpaint workflows |
| 5 | `compositor.py` | memmap canvas, PyTorch blend, BigTIFF export |
| 6 | Frontend | Blueprint Studio + Mission Control + tile matrix |
| 7 | Export Bay | GPU downscale endpoint + modal UI |

---

## 11. Repository Structure (Target)

```
art_ai_mosaic_r1/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── routers/
│   │   │   ├── mosaic_router.py
│   │   │   └── export_router.py
│   │   ├── services/
│   │   │   ├── xai_adapter.py
│   │   │   ├── local_gpu.py
│   │   │   ├── compositor.py
│   │   │   └── scheduler.py
│   │   ├── models/
│   │   │   ├── canvas.py
│   │   │   └── tile.py
│   │   └── core/
│   │       ├── grid_math.py
│   │       └── config.py
│   ├── workflows/          # ComfyUI exported JSON
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── BlueprintStudio.tsx
│   │   │   ├── MissionControl.tsx
│   │   │   ├── TileMatrix.tsx
│   │   │   └── ExportBay.tsx
│   │   └── App.tsx
│   └── package.json
├── scripts/
│   └── phase0_spike.py     # Feasibility validation
├── doc/
│   ├── MASTER_PLAN.md      # This document
│   ├── mosaic-image-engine-plan.md
│   └── mosaic-image-engine-plan2_complete.md
├── .env.example
├── .gitignore
└── README.md
```

---

## 12. Environment Setup Checklist

- [ ] NVIDIA driver (Game Ready or Studio)
- [ ] CUDA toolkit (cu12x PyTorch wheel)
- [ ] Python 3.10+ venv
- [ ] ComfyUI Windows portable (`.7z`)
- [ ] Model downloads: SDXL checkpoint, ControlNet Tile, Real-ESRGAN weights
- [ ] xAI API key in `.env`
- [ ] Node.js 18+ for frontend

---

## 13. Immediate Next Action

**Run Phase 0** as `scripts/phase0_spike.py`:

1. Generate one 2K blueprint
2. Generate 3×3 context-conditioned tiles
3. Run ComfyUI inpaint on seams
4. Produce side-by-side comparison (raw vs repaired)

This single artifact validates both the cloud-tiling assumption and the RTX 4080 integration plan.

---

## Appendix A — Document Cross-Reference

| Topic | Plan 1 (research) | Plan 2 (UX/spec) |
|-------|-------------------|------------------|
| API constraints | §1 | §1 |
| Canvas formats | §2 | §4 |
| Pipeline stages | §3 | §3 |
| Regional prompts | §4 | — (Phase 2) |
| Consistency | §5 | — |
| Local GPU | §6 | §3 Stage 3 |
| Tech stack | §7 | §5 |
| Cost examples | §8 | §6 |
| Risks | §9 | — |
| Phases | §10 | §7 |
| UX flows | — | §2 |
| Cursor build steps | — | §7 |

---

## Appendix B — Key Constants

```python
BASE_TILE_PX = 2048
LOCAL_UPSCALE_FACTOR = 2          # default; tunable 1–4
OVERLAP_FRACTION = 0.25           # 20–30% recommended
PLACEHOLDER_SIZE = 512            # black neighbor placeholder
BLUEPRINT_RESOLUTION = "2k"
DEFAULT_TILE_AR = "1:1"
COMFYUI_URL = "http://127.0.0.1:8188"
STYLE_ANCHOR = ""                 # set per job; appended to every prompt
```
