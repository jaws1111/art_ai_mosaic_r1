# Multi-Megapixel Mosaic Image Engine — Research & Architecture Plan

**Goal:** generate single coherent images at >10,000×10,000px (arbitrary, user-selectable aspect ratio — including custom pixel dimensions and 360° formats in Phase 2) by orchestrating many individual xAI (`grok-imagine-image-quality`) generations into a seamless master composite, accelerated locally on an RTX 4080 (Windows 10) for upscaling, seam-fixing, and compositing.

---

## 1. Research Findings: xAI Imagine API Constraints

These facts (pulled from current xAI docs, May–June 2026) are the load-bearing constraints for the whole architecture — design around them rather than discovering them mid-build.

| Capability | Finding | Implication |
|---|---|---|
| **Max native resolution** | Only `1k` (1024px) and `2k` (2048px) resolution presets exist. No 4K/8K/custom pixel dimensions. | A >10,000px canvas is **mathematically required to be a mosaic** of dozens of 2K tiles, *unless* local upscaling reduces the tile count needed (see §6). |
| **Aspect ratio** | Fixed enum: `1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3, 2:1, 1:2, 19.5:9, 9:19.5, 20:9, 9:20, auto`. No arbitrary W:H. | Final canvas can be *any* aspect ratio (you control it via grid dimensions), but each individual **tile request** must use one of these enum ratios. Square (`1:1`) tiles are simplest for a uniform grid. |
| **Two endpoints** | `POST /v1/images/generations` (text→image) and `POST /v1/images/edits` (image-conditioned). | Text-to-image is used once, for the master blueprint. Every tile after that uses `/edits` so it can be conditioned on neighbor/context images. |
| **Multi-image context** | `/edits` accepts up to **3 source images** (`image_url`, base64, or `file_id`) in a single call. | Mechanism for consistency: feed each tile generation (a) a downscaled crop of the master blueprint, (b) the overlapping edge of the left neighbor, (c) the overlapping edge of the top neighbor. |
| **Aspect ratio control on edit calls** | With a **single** source image, output AR is forced to match the input image's AR. With **multiple** source images, `aspect_ratio` is respected. | Always pass ≥2 context images per tile call, never just 1, or you lose AR control. |
| **No mask/inpainting parameter** | Editing is whole-image, prompt-driven. There is **no documented region mask / inpaint API**. | No native "fill exactly this rectangle and blend into these exact pixels" primitive in the cloud API. This is the single biggest cloud-side risk — and exactly what the local RTX 4080 pipeline in §6 is positioned to fix. |
| **No seed parameter** | Not exposed in the docs reviewed. | Can't lock a generation seed for reproducibility/determinism. Consistency must come from context images + a tight, repeated style/prompt scaffold. |
| **Generated URLs are temporary** | Docs explicitly warn: "download or process promptly." | The orchestrator must immediately persist every tile before using it as context for the *next* tile. |
| **Files API** | Supports referencing stored files by `file_id` and creating permanent public URLs, usable directly as Imagine inputs. | Use instead of re-uploading base64 blobs for every neighbor reference. |
| **Pricing** | ~$0.02 per generated image (1K or 2K, same price) + $0.002 per input context image. | Cheap at scale. Cost is not the constraint; *time*, *rate limits*, and *seam quality* are. |
| **Rate limits** | Imagine API limits are account-tier-based (contact sales for increases); legacy model docs cite 300 RPM as a reference point. `429` → exponential backoff. | Large canvases need a job queue with backoff, not a naive synchronous loop. |
| **Batch (`n` param)** | Generates *variations of the same prompt*, not distinct tiles. | Don't use for mosaic tiles — each tile needs distinct prompt + context images via scheduled, separate requests. |

**Bottom line:** the cloud API gives a strong creative building block but no native large-canvas, custom-resolution, or inpainting primitive. The product is **hierarchical tiled generation via context-image conditioning, with the heavy lifting of resolution-stretching and seam repair done locally on the RTX 4080** rather than the cloud API.

---

## 2. Output Canvas Format & Aspect Ratio System

The canvas spec is a first-class input to the whole pipeline, not an afterthought — everything downstream (grid size, tile count, cost/time estimate) derives from it.

### 2.1 Format selector (Phase 1)

| Mode | Description |
|---|---|
| **Custom W×H** | User enters any pixel width and height directly (e.g., `14000 × 8400`). This is the general case — the canvas itself is *not* constrained to the xAI aspect-ratio enum; only individual tile *requests* are (handled internally, invisible to the user). |
| **Preset aspect ratios** | One-click buttons for the ratios you called out as typical: **16:9**, **9:16**, **1:1**, **32:9** (super-ultrawide), plus secondary presets (21:9, 3:2, 4:3, 2:1) for convenience. Selecting a preset + a target long-edge resolution (e.g. "12,000px long edge") auto-computes exact W×H. |
| **Target resolution control** | Independent of aspect ratio: a slider/field for "long edge px" (e.g. 10K / 12K / 16K / 20K) or a direct total-megapixel target, so the user isn't doing the W×H math by hand. |

Internal data model:

```text
CanvasFormat {
  mode: "standard" | "panorama_h" | "panorama_v" | "spherical"   # latter 3 = Phase 2
  width_px: int
  height_px: int
  aspect_label: "16:9" | "9:16" | "1:1" | "32:9" | "custom" | ...
  wraparound: bool        # true only for panorama_h / panorama_v / spherical
}
```

`mode = "standard"` covers everything in Phase 1: any custom W×H, any of the preset ratios, no wraparound constraint. This is the only mode needed to hit the >10,000×10,000 / 32:9 / arbitrary-ratio requirement.

### 2.2 360° formats (Phase 2 — flagged, not built first)

These are deliberately scoped out of Phase 1 because they add a real extra dimension of technical complexity beyond "bigger canvas": **edge continuity becomes a hard geometric requirement, not just a quality nicety.**

- **360° Horizontal (cylindrical panorama):** the canvas wraps left-to-right — the rightmost column of pixels must blend into the leftmost column. This means the tile dependency graph in §3.1 gains one more edge: the rightmost tile column also depends on the leftmost tile column (a "closing the loop" pass after the main grid completes), conditioned on both neighbors simultaneously.
- **360° Vertical (cylindrical panorama, vertical axis):** same idea, rotated 90° — top and bottom rows wrap into each other instead of left/right.
- **Full 360° Spherical (equirectangular, for VR/360 viewers):** fixed 2:1 aspect ratio, wraps left-right *and* has severe pixel-density distortion near the top/bottom poles (a single pixel row at the very top/bottom represents an entire point in 3D space — content there gets heavily warped). Tiling the equirectangular canvas directly produces visibly wrong perspective and seams near the poles.

  **Recommended approach when this is built:** don't tile the equirectangular image directly. Generate **6 cubemap faces** instead (front/back/left/right/up/down), each a flat, undistorted square canvas that reuses the *entire* Phase 1 architecture unmodified (master blueprint + tile grid + local upscale/inpaint, per face, with continuity constraints enforced at shared cube edges the same way tile neighbors are handled). Then reproject all 6 faces into a single equirectangular image with a standard cubemap→equirectangular remap — a well-understood, GPU-cheap operation (`cv2.remap` or a `torch.nn.functional.grid_sample` warp) that the RTX 4080 handles essentially instantly. This sidesteps the pole-distortion problem entirely instead of trying to solve it inside the diffusion/tiling step.

Phase 2 scope note: build horizontal/vertical wraparound first (smaller delta from Phase 1 — just one extra dependency edge + a closing pass), spherical/cubemap last (genuinely new pipeline branch).

---

## 3. Core Architecture: Hierarchical Tiled Mosaic

```
User Prompt(s) + Canvas Format (§2)
        │
        ▼
┌─────────────────────┐
│ Stage 0: Canvas Plan │  → grid: tile size, overlap %, rows×cols, dependency graph
└─────────────────────┘
        │
        ▼
┌──────────────────────────┐
│ Stage 1: Master Blueprint │  → ONE text-to-image call at 2K, canvas's approximate AR.
│  (global composition,     │     Low-fidelity compositional guide only — never shown
│   palette, lighting)      │     as final output.
└──────────────────────────┘
        │
        ▼
┌────────────────────────────────┐
│ Stage 2: Cloud Tile Generation   │  → xAI /images/edits, ≤3 context images per tile,
│  (xAI, content + composition)   │     wavefront-scheduled (see §3.3)
└────────────────────────────────┘
        │
        ▼
┌────────────────────────────────┐
│ Stage 2.5: Local GPU Upscale     │  → RTX 4080, Real-ESRGAN / ControlNet-Tile workflow,
│  (RTX 4080, resolution stretch)  │     multiplies each 2K tile 2–4x before compositing
└────────────────────────────────┘
        │
        ▼
┌──────────────────────────┐
│ Stage 3: Seam Repair       │  → PRIMARY: local SDXL/FLUX inpainting (real mask, RTX 4080)
│  (local-first, RTX 4080)   │     FALLBACK: classical feather blend + color-transfer
└──────────────────────────┘
        │
        ▼
┌──────────────────────────┐
│ Stage 4: Streaming Composite│ → write directly into a tiled/pyramidal output,
│  (Windows-native, low RAM) │    never materialize the full canvas in memory
└──────────────────────────┘
        │
        ▼
┌──────────────────────────┐
│ Stage 5: Delivery          │ → pyramidal/tiled BigTIFF for deep-zoom viewer,
│                            │    + flattened JPEG/PNG export
└──────────────────────────┘
```

### 3.1 Stage 0 — Canvas Planning

Inputs: `(width_px, height_px)` from §2, overlap fraction `o` (recommend 0.20–0.30), and the **effective tile size after any planned local upscale** (see §6.2 — this is the key lever that changes tile count dramatically).

```text
tile_size_effective = base_tile_px (2048) * local_upscale_factor   # e.g. 2048 * 2 = 4096
stride = tile_size_effective * (1 - o)
cols = ceil((width_px  - tile_size_effective) / stride) + 1
rows = ceil((height_px - tile_size_effective) / stride) + 1
```

Dependency graph: tile `(r,c)` depends on `(r,c-1)` and `(r-1,c)`. Anti-diagonal tiles are mutually independent → wavefront-parallel scheduling.

### 3.2 Stage 1 — Master Blueprint

One `/images/generations` call at 2K, nearest enum `aspect_ratio` to the canvas's true ratio. Pure compositional guide (focal point, horizon, palette, lighting direction) — every tile downstream gets a resized crop of it as anchor context, which is what keeps 10–50+ independent generations from drifting into unrelated compositions. A fixed "style anchor" text block (medium, lighting, palette, rendering style) is appended verbatim to the blueprint prompt and every tile prompt.

### 3.3 Stage 2 — Cloud Tile Generation

For tile `(r,c)`, call `/v1/images/edits` with:
- `prompt`: style anchor + region content (§4) + "continue seamlessly from the adjacent reference edges shown; match their exact color grading, lighting, and texture at the boundary."
- `images`: blueprint crop (always) + left-neighbor overlap strip (if exists) + top-neighbor overlap strip (if exists).
- `aspect_ratio`: `"1:1"` (or grid's chosen ratio) — valid because ≥2 images are always supplied.

Persist immediately (download or push through Files API) — never depend on the URL surviving the rest of the job.

### 3.4 Stage 2.5 / 3 — see §6 for the full local-GPU design (this is the substantial addition this revision makes to the pipeline).

### 3.5 Stage 4 — Streaming Composition

Write tiles directly into a disk-backed canvas as they complete rather than holding everything in RAM — see §7 for the Windows-native (no Linux-lib) approach.

### 3.6 Stage 5 — Delivery

Browsers can't usefully render a 100+ megapixel image directly. Output a pyramidal/tiled BigTIFF for a pan/zoom viewer (OpenSeadragon) plus a flattened JPEG/PNG export.

---

## 4. Regional Prompting — "Mosaic of Prompts"

Since picture content is defined by "prompt(s)" plural, this is designed in from day one: a lightweight layout canvas where the user assigns different prompts to different regions ("mountains here," "city skyline there"), similar in spirit to regional/ControlNet-style prompting, implemented purely through the tiling + context-image scaffold:

1. User paints regions on a low-res layout grid, each tagged with a sub-prompt.
2. Stage 1's blueprint generation becomes region-aware (combined prompt, or a crude color-coded region map passed as a visual reference).
3. Each tile's content prompt = blend of whichever region(s) its grid cell overlaps, with straddling tiles explicitly told to transition ("from X on the left to Y on the right").

Phase 2 milestone, alongside the 360° formats (§2.2) — treat both as the two Phase 2 tracks, buildable in parallel since they touch different parts of the system (content/UI vs. geometry/projection).

---

## 5. Consistency Strategy (Summary)

No seed control, no cloud-side inpainting mask — consistency is achieved through redundancy and anchoring across both the cloud and local stages:

- **Style anchor string**: fixed, verbatim, every prompt (cloud and local).
- **Blueprint conditioning**: every tile sees a crop of the same master image.
- **Neighbor conditioning**: every cloud tile sees real pixels from already-generated neighbors.
- **Local seam inpainting** (§6): the real fix for boundary mismatches the cloud API can't guarantee.
- **Color harmonization pass**: classical, deterministic, GPU-accelerated (§6.4).
- **Optional local IP-Adapter style-lock**: an RTX-4080-side supplement that conditions local upscale/inpaint passes on a fixed style reference image, independent of whatever drift happens cloud-side.
- **Retry-on-drift**: automated overlap-similarity check; regenerate a tile once with a stronger match instruction if it falls below threshold.

---

## 6. Local RTX 4080 Acceleration Strategy (Windows 10, no Linux deps)

This is the most consequential addition to the architecture. The cloud API is excellent at creative content generation and bad at the two things this project needs most at scale: **arbitrary resolution** and **precise seam control**. The RTX 4080 is good at exactly those two things, and Windows-native tooling exists for both without touching WSL or Linux-only libraries.

### 6.1 What a 16GB RTX 4080 can actually run, locally, on Windows

Current research (mid-2026) is consistent on this point: **16GB VRAM is the established "comfortable" tier** for SDXL with ControlNet, LoRAs, and inpainting loaded simultaneously, and for FLUX.1 models at FP8 quantization. This isn't a stretch use case for this card — it's the documented sweet spot. All of the tools below (ComfyUI, Forge/A1111, InvokeAI) ship native Windows builds (including portable, no-install Windows packages for ComfyUI) and run on CUDA directly — **no WSL, no Linux libraries, no dual-boot required.**

Practical headroom check for your box: 16GB VRAM is fine; pair it with 32GB+ system RAM (ComfyUI stages model weights through system RAM before VRAM) for smooth operation alongside everything else.

### 6.2 Local upscaling — multiplies resolution without multiplying xAI calls

Instead of relying purely on dozens of native 2K xAI tiles to fill a >10,000px canvas, generate a *moderate* grid of 2K tiles for content/compositional variety, then locally upscale each tile 2–4x with a GPU upscaler before compositing:

- **Real-ESRGAN** (x4plus / x4plus-anime checkpoints) — the standard choice; runs via a Windows-native `realesrgan-ncnn-vulkan.exe` (zero Python/CUDA setup, just Vulkan, dependency-free) or as a ComfyUI node (tighter pipeline integration, recommended if everything else routes through ComfyUI anyway).
- Alternatives worth knowing about: SwinIR, 4x-UltraSharp — same role, marginal quality/speed tradeoffs.

**This is a real tradeoff, not a free lunch**: pushing the upscale factor up reduces the number of xAI calls needed (good for cost/time) but also reduces the number of independently-prompted content regions (bad for the regional-mosaic vision in §4) — a 4x upscale can shrink a 49-tile grid down to ~4 tiles, which is efficient but defeats the point if the goal is many distinct hand-prompted regions. Recommend keeping upscale factor modest (2x) by default and exposing it as a tunable, not maxing it out.

### 6.3 Local seam inpainting — the real fix for the cloud API's missing mask primitive

This directly resolves the top risk flagged in §1: xAI's `/edits` has no mask-based inpainting. A local SDXL or FLUX checkpoint, run through ComfyUI's `InpaintModelConditioning` node, does:

1. After two adjacent tiles are placed (with their overlap region roughly blended), generate a precise mask covering just the seam band.
2. Run local inpainting on exactly that masked strip, conditioned on the real pixels on both sides — true masked fill, not "hope the prompt instruction was followed."
3. **ControlNet Tile** is the specific tool built for this scenario (tiled upscaling/consistency) and is worth using here directly rather than vanilla inpainting — it's purpose-built to keep diffusion output coherent with its surrounding tile context.

This runs entirely on the RTX 4080, free of additional API cost and rate limits, and is materially more reliable than the classical-blending-only fallback originally proposed.

### 6.4 GPU-accelerated classical operations

Even the "boring" parts of the pipeline benefit: feathering, histogram/color-transfer matching, and graph-cut seam-path search are all trivially parallel operations that run far faster as PyTorch CUDA tensor ops than as CPU/NumPy loops once canvases exceed ~15,000–20,000px. Recommend doing this math in PyTorch (already a dependency for the local models) rather than introducing a separate CPU image library for it.

### 6.5 Architecture integration

Run ComfyUI locally in **API/headless mode** (it exposes an HTTP server, default `localhost:8188`, that accepts workflow JSON and returns results) as a local "inference microservice" sitting alongside the cloud xAI calls. The FastAPI orchestrator (§7) talks to two backends behind one interface:

```text
TileGenerator (interface)
 ├── CloudGenerator   → xAI /images/generations, /images/edits   (creative content)
 └── LocalGenerator   → ComfyUI HTTP API on localhost:8188        (upscale, inpaint, color-match)
```

This keeps the division of labor clean: **xAI owns "what's in the picture,"** **the RTX 4080 owns "how big and how seamless."**

### 6.6 Setup checklist (Windows 10)

- NVIDIA driver + CUDA toolkit (current Game Ready or Studio driver is sufficient; no separate Linux CUDA toolkit needed).
- ComfyUI portable Windows build (`.7z`, self-contained, includes embedded Python — easiest path; avoids any system Python/venv conflicts).
- PyTorch with CUDA wheel (`pip install torch --index-url ...cu12x`) if you also want non-ComfyUI scripted GPU ops (blending math) in the orchestrator process directly.
- Model downloads: an SDXL checkpoint, ControlNet Tile model, Real-ESRGAN weights — all standard `.safetensors`/`.pth` files, no compilation step.
- No `pyvips`/`libvips`, no GDAL, no Linux-targeted compositing libraries — see §7 for the Windows-native equivalents used instead.

---

## 7. System Architecture / Tech Stack

| Layer | Recommendation | Why |
|---|---|---|
| Orchestration backend | Python, FastAPI | Async-friendly, easy xAI SDK + ComfyUI HTTP API integration, job-state API for the frontend to poll. |
| Job queue / scheduling | `asyncio` + semaphore-bounded wavefront scheduler (the dependency graph is small enough not to need Celery/Dagster) | Maximizes throughput within xAI rate limits while respecting tile dependencies. |
| Job/tile state | SQLite (single-user/local — fits this being a Windows desktop tool) | Resumable jobs once you're at 50+ tiles and a 429 or moderation rejection happens mid-run. |
| **Local GPU inference** | **ComfyUI (Windows portable build), headless/API mode, on the RTX 4080** | Real-ESRGAN upscaling, SDXL/FLUX + ControlNet-Tile inpainting, optional IP-Adapter style lock — see §6. |
| Heavy image math | **PyTorch (CUDA)** for blending/color-transfer/seam-search tensor ops | Native Windows CUDA support, already a dependency via ComfyUI, no Linux-only libs. |
| General image IO | **OpenCV (`opencv-python`)**, **Pillow**, **NumPy** | Standard Windows wheels via pip, no system library installs required. |
| Large-canvas streaming write | **`tifffile`** (pure pip-installable, Windows-wheel friendly) writing tiled/pyramidal BigTIFF directly, backed by `numpy.memmap` for the working canvas so the full 100+MP image is never fully resident in RAM | Avoids `pyvips`/libvips entirely (explicitly avoiding Linux-oriented native-lib dependencies) while still getting streaming, low-memory composition. |
| Storage | Local filesystem (tiles + final BigTIFF) | Matches a local Windows desktop-tool deployment; revisit only if this becomes a hosted multi-user service. |
| Frontend | Single-page app (dark-themed control panel, consistent with your usual build pattern); OpenSeadragon embed for the deep-zoom result viewer | Canvas-format selector (§2), region painter (§4), live tile-grid progress view, cost/time estimator before commit. |
| Rate-limit handling | Exponential backoff on `429` from the cloud side only — local ComfyUI calls aren't rate-limited, just VRAM/queue-depth bound | Required given large fan-out of cloud tile calls; local stage just queues. |

---

## 8. Worked Examples (Cost, Tile Count, Hybrid Benefit)

`base_tile_px = 2048`, `overlap = 25%`. Compare pure-cloud tiling vs. cloud+local-2x-upscale hybrid:

| Target canvas | Pure-cloud tile grid | Pure-cloud tiles | Hybrid (2x local upscale) grid | Hybrid tiles | Est. cloud cost (hybrid) |
|---|---|---|---|---|---|
| 10,000 × 10,000 (1:1) | 7×7 | 49 | 4×4 | 16 | ~$0.42 |
| 12,000 × 8,000 (3:2) | 8×5 | 40 | 5×3 | 15 | ~$0.39 |
| 21,300 × 6,000 (32:9) | 14×4 | 56 | 8×2 | 16 | ~$0.42 |
| 16,000 × 9,000 (16:9) | 10×5 | 50 | 6×3 | 18 | ~$0.47 |

(Cost ≈ tiles × $0.026, including ~3 context images per call. The hybrid column roughly **3x reduces cloud call count** at a 2x local upscale factor, which is the recommended default — see the tradeoff note in §6.2 before pushing the upscale factor higher.)

**Cost was already a non-issue; the hybrid approach mainly buys back wall-clock time and rate-limit headroom**, while simultaneously giving you the local inpainting pass (§6.3) that materially improves seam quality — the two benefits compound rather than trade off against each other.

---

## 9. Risks & Open Questions

1. **Cloud-side seam quality is still the open empirical question for Stage 2 output**, but is now a *softer* risk than originally — local inpainting (§6.3) is the designed fix rather than a hoped-for prompt behavior. Still worth a Phase 0 spike to confirm how much local repair is actually needed per tile.
2. **No seed = no reproducibility** on the cloud side; design retries to accept variance, not expect determinism.
3. **Moderation rejections mid-grid** need a clean retry/reprompt path, not a job-ending failure.
4. **Single-image edit calls silently lock output AR** — always pass ≥2 context images per cloud tile call.
5. **URL expiry** — persist every cloud tile immediately.
6. **Imagine API rate-limit headroom isn't published in the standard tier table** — confirm actual RPM/concurrency with xAI before sizing the wavefront scheduler.
7. **New, local-stage risks introduced by §6:** VRAM contention if ComfyUI's loaded checkpoint plus the orchestrator's own PyTorch tensor ops run concurrently (mitigate by sizing local batch/queue depth conservatively, monitoring VRAM headroom); first-run model download/setup overhead (SDXL + ControlNet-Tile + Real-ESRGAN weights total several GB — one-time cost); Windows process management for spawning/health-checking the ComfyUI subprocess from the FastAPI orchestrator.
8. **Upscale-factor vs. content-granularity tradeoff (§6.2)** needs a sensible default and clear UI exposure so users don't accidentally trade away the "many distinct prompted regions" feature for raw resolution.

---

## 10. Phased Delivery Roadmap

- **Phase 0 — Feasibility spike (days):** smallest possible Stage 1+2 — one blueprint + a 3×3 cloud tile grid with overlap-based context conditioning — visually inspect seam quality *before* deciding how much local repair work Stage 3 actually needs to do.
- **Phase 1 — Core pipeline, standard formats, local GPU integrated from the start:** canvas format selector (§2.1: custom W×H + 16:9/9:16/1:1/32:9 presets), wavefront cloud tile scheduler, ComfyUI local service for upscale + inpaint + color-match, streaming BigTIFF composite. Single global prompt only; no regional painter yet.
- **Phase 2 — two parallel tracks:**
  - **2a. Regional prompt mosaic** (§4): layout/region painter, per-region prompts, tile-grid progress view.
  - **2b. 360° formats** (§2.2): horizontal/vertical wraparound first, then full spherical via the cubemap→equirectangular approach.
- **Phase 3 — Scale & resilience:** resumable jobs, retry/backoff hardening, larger canvases (20,000px+), automated overlap-similarity QA with auto-regeneration of bad tiles.
- **Phase 4 — Polish:** style presets, cost/time estimator before commit, export formats, job history, exposed upscale-factor tuning (§6.2/§9.8).

---

## 11. Suggested Next Step

Run **Phase 0** as a standalone script: one blueprint generation + a 3×3 grid of context-conditioned `/edits` calls. Then run that same 3×3 grid's seams through a quick local ComfyUI inpaint pass to see the *delta* a local repair stage actually buys you. That comparison — raw cloud seams vs. locally repaired seams — is the single artifact that validates (or reshapes) both the cloud-tiling assumption and the RTX 4080 integration plan in one shot.
