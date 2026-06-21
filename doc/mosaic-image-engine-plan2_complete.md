```markdown
# Tessera v3: Multi-Megapixel Mosaic Engine
## Complete Architectural Specification & UX/UI Plan

**Objective:** Build a Windows 10 desktop/web-hybrid application that generates seamless, coherent images exceeding 10,000×10,000 pixels at arbitrary aspect ratios. It orchestrates the xAI `grok-imagine-image-quality` API for creative generation via context-image chaining, and leverages a local RTX 4080 (via headless ComfyUI) for AI upscaling, precise seam inpainting, GPU-accelerated compositing, and high-speed export.

**Design Philosophy:** Transform a complex, asynchronous, multi-minute compute task into a professional, "mission-control" style interface. The user should never feel blind during generation; they should feel like a director watching a crew build their vision.

---

## 1. Hard Constraints & API Realities (The Load-Bearing Walls)

*These facts from xAI documentation dictate the entire system architecture. The codebase must be designed around them, not against them.*

| Capability | Reality | Architectural Rule |
| :--- | :--- | :--- |
| **Max Native Resolution** | Only `1k` (1024px) and `2k` (2048px) presets exist. No custom pixel dimensions. | Mosaic tiling is mathematically mandatory. Use `2k` for base tiles. |
| **Aspect Ratio (AR)** | Fixed enum only (`1:1`, `16:9`, `9:16`, `4:3`, `3:2`, `2:1`, `auto`, etc.). No arbitrary W:H. | Final canvas is user-defined (any px), but *individual tile API calls* must use an enum (default to `1:1`). |
| **Endpoints** | `/v1/images/generations` (text→image) and `/v1/images/edits` (image-conditioned). | Use `/generations` once for the Master Blueprint. Use `/edits` for all subsequent tiles. |
| **Multi-image Context** | `/edits` accepts max **3 source images** per call. | Pass exactly 3 images to every tile: (1) Blueprint crop, (2) Left neighbor strip, (3) Top neighbor strip. |
| **The AR Lock Bug** | If you pass *one* image to `/edits`, output AR locks to the input image's AR. With *multiple* images, it respects the requested AR. | **Never pass 1 image.** Always pass 2 or 3 to force the API to respect the `aspect_ratio` parameter. |
| **No Mask/Inpainting** | Editing is whole-image, prompt-driven only. No regional mask primitive. | Cloud API cannot guarantee perfect seams. This is the exact reason the local RTX 4080 inpainting pipeline exists. |
| **No Seed Parameter** | Not exposed in current docs. | Consistency relies 100% on visual context chaining, not deterministic generation. |
| **Temp URLs** | Generated image URLs expire quickly. | Orchestrator must download and persist to local NVMe disk *immediately* upon generation. |
| **Rate Limits** | Tier-based RPM limits. Returns `429 Too Many Requests`. | Requires a wavefront scheduler with strict exponential backoff and job resumability. |

---

## 2. UX/UI Architecture & User Flows

The frontend is a React application built with Tailwind CSS, designed to make the asynchronous pipeline transparent and controllable.

### 2.1 The Blueprint Studio (Initial Image Sourcing)
Before tiling begins, the user defines the global composition via a prominent segmented control in the left sidebar: **[ 🤖 AI Generate ]** | **[ 📁 Upload Image ]**

**Path A: AI Generate**
*   Large text area for the master prompt.
*   Drag-and-drop zone for 1-3 style/context reference images.
*   Dropdown restricted *strictly* to the xAI API enum (`1:1`, `16:9`, `3:2`, etc.). *Tooltip: "Defines the shape of the AI blueprint. Your final canvas can be any size."*
*   Action: "Generate Blueprint" → Calls `/v1/images/generations` → Displays 2K preview.

**Path B: Upload / Load from Disk**
*   User drops a high-res image (e.g., a 4K photo).
*   System reads dimensions, calculates exact AR, and auto-selects the closest xAI enum AR for subsequent API calls to prevent warping.

**The "Lock & Commit" Gate**
Below the preview is a prominent **"🔒 Lock Blueprint & Configure Canvas"** button. This freezes the source, closes the sidebar, and transitions to Canvas Configuration.

### 2.2 Mosaic Mission Control (Progress & Inspection)
Once the user sets final pixel dimensions (e.g., 14,000 x 6,000) and hits "Generate Mosaic", the UI transforms into a real-time dashboard.

*   **The Main Viewport (OpenSeadragon):** Deep-zoom viewer. As the backend composites tiles into the `BigTIFF`, the frontend dynamically loads them. The user can pan and zoom *while the image is still generating* to inspect seam quality.
*   **Grid Overlay Toggle:** Checkbox to show/hide subtle wireframes of tile boundaries and overlap zones.
*   **The Tile Status Matrix (Mini-Map):** Bottom-right corner grid showing real-time tile states via WebSocket:
    *   ⬛ Dark Gray: Queued.
    *   🔵 Pulsing Blue: xAI Cloud API generating.
    *   🟡 Yellow: Queued for Local RTX 4080.
    *   🟠 Orange: Local GPU Upscaling / Inpainting.
    *   🟢 Green: Fully composited.
    *   🔴 Red: Error (Click for popover with error log and "Retry Tile" button).
*   **The Metrics Bar (Top HUD):** `Elapsed: 4m 12s | Est. Remaining: 6m 30s | Stage: Local Inpaint (GPU Load: 82%) | API Calls: 38 | Est. Cost: $0.98`

### 2.3 The Export Bay (RTX 4080 Accelerated)
A modal providing exhaustive, GPU-accelerated downscaling and format conversion. The user can select multiple combinations simultaneously.

*   **Formats:** JPEG (Quality Slider 10-100%), PNG (Lossless), WebP (Quality Slider), Master BigTIFF.
*   **Sizes:** Original (100%), 8K UHD, 4K UHD, 1440p, 1080p, or Custom WxH (maintains aspect ratio lock).
*   **Action:** **"⚡ Generate with GPU Acceleration"**
*   *Backend Magic:* The FastAPI backend loads the massive `numpy.memmap` directly into RTX 4080 VRAM as PyTorch tensors. It uses `torch.nn.functional.interpolate(mode='bicubic')` to downscale a 10k image to 4k in **< 0.2 seconds** (compared to 5-10 seconds locking up the CPU). It then streams the zip to the browser.

---

## 3. Core System Architecture (The 5-Stage Pipeline)

**The Core Philosophy:** xAI generates *what* is in the picture. The RTX 4080 handles *how big* it is and *how seamless* it looks.

### Stage 0: Grid Math Engine
Calculates the tiling array based on target W/H.
*   `tile_base = 2048`
*   `local_upscale_factor = 2` (Default, configurable)
*   `tile_effective = 4096` (2048 * 2)
*   `overlap = 0.25` (25% overlap for seam repair space)
*   `stride = tile_effective * (1 - overlap)`
*   Calculates `rows` and `cols`. Generates a dependency graph (Tile `[r,c]` requires Tile `[r-1,c]` and `[r,c-1]`).

### Stage 1: Master Blueprint (Cloud)
*   Makes *one* call to `/v1/images/generations` at `2k` using the closest matching xAI enum AR.
*   **Purpose:** Global composition, color palette, and lighting anchor.
*   Saved locally to disk; never shown to user as final output.

### Stage 2: Wavefront Cloud Tiling (Cloud)
Uses **Wavefront Scheduling** (Anti-diagonal execution). Tiles with no dependencies run in parallel up to rate limits.
For each Tile `[r,c]`, the API Adapter constructs:
1.  **Prompt:** `[Global Style Anchor] + [Spatial Context: e.g., "top left corner..."] + [Seam Directive: "match exact colors/lines of provided edge references"]`
2.  **Image 1:** Crop of Master Blueprint corresponding to `[r,c]`.
3.  **Image 2:** Overlap strip from Left Neighbor `[r,c-1]` (or black placeholder if none).
4.  **Image 3:** Overlap strip from Top Neighbor `[r-1,c]` (or black placeholder if none).
5.  **Call:** `POST /v1/images/edits` with `aspect_ratio: "1:1"`. Save result to disk immediately.

### Stage 3: Local RTX 4080 Refinery (Local ComfyUI)
As tiles complete Stage 2, they are queued locally via ComfyUI portable API (`localhost:8188`):
1.  **AI Upscale:** Run 2048px tile through Real-ESRGAN/4x-UltraSharp (2x scale) to reach `tile_effective` size (4096px).
2.  **Seam Inpainting:** Because the cloud API lacks masks, we fix seams locally.
    *   Take two adjacent upscaled tiles.
    *   Generate a mask covering their overlap zone.
    *   Run SDXL/FLUX Inpaint + ControlNet Tile node conditioned on unmasked parts of both tiles.
    *   *Result:* Mathematically perfect, diffusion-generated seams.

### Stage 4: GPU-Accelerated Streaming Composite (Local)
*Cursor Directive: Do NOT use standard PIL/Image.new() for the final canvas. It will crash Windows.*
1.  Use `numpy.memmap` to create a memory-mapped array on disk (e.g., `canvas.dat`). Allows manipulation of 100MP+ image without loading into RAM.
2.  Use **PyTorch CUDA** for blending math. Load overlap regions into RTX 4080 VRAM, apply Linear Gradient Feathering (Alpha blending) as tensor operations.
3.  Write blended pixels directly into the `memmap`.
4.  Use pure-Python `tifffile` library to wrap the `memmap` into a streaming, pyramidal **BigTIFF** file.

### Stage 5: Delivery & Deep Zoom
*   BigTIFF served to frontend.
*   OpenSeadragon dynamically loads only the pixels visible on screen, allowing smooth panning across a 30,000px image in a browser tab.

---

## 4. Canvas & Aspect Ratio System

The user controls the final output; the system handles the math.

### Phase 1: Standard & Arbitrary
*   **Presets:** 16:9, 9:16, 1:1, 32:9, 4:3.
*   **Custom:** User inputs exact `Width` and `Height` in pixels (e.g., `14,000 x 4,500`).
*   **Long-Edge Slider:** User picks target Megapixels or Long-Edge (10K, 12K, 16K), system calculates the other dimension based on selected ratio.
*   *Internal Data Model:* `CanvasFormat { width_px: int, height_px: int, mode: "standard" }`

### Phase 2: 360° Formats (Architectural Prep)
*   **Horizontal/Vertical Pano:** Standard tiling, but the grid dependency graph wraps around (Tile `0,X` neighbors Tile `Max,X`).
*   **Spherical (Equirectangular):** **DO NOT tile the 2:1 equirectangular image directly** (severe pole distortion). Instead, generate 6 independent flat square canvases (Cubemap faces) using the standard Phase 1 pipeline, then use a PyTorch `grid_sample` warp on the RTX 4080 to reproject the cubemap into a 2:1 spherical image instantly.

---

## 5. Technology Stack (Windows 10 Strict)

**Explicitly Banned (Linux-only/WSL dependencies):** `pyvips`, `libvips`, `gdal`, Linux-specific `torch` compilations.

| Layer | Technology | Purpose & Why |
| :--- | :--- | :--- |
| **Backend API** | Python 3.10+, FastAPI, Uvicorn | Async native, handles concurrent cloud API calls & WebSockets. |
| **Local GPU** | ComfyUI (Windows Portable `.7z`) | Self-contained inference microservice. No system Python conflicts. Runs headless. |
| **Job Scheduling** | Native `asyncio` + Semaphores | Dependency graph is small enough that Celery/Redis is overkill. Handles wavefront logic. |
| **State/DB** | SQLite (via `aiosqlite`) | Tracks tile statuses for resumable jobs and UI matrix updates. |
| **GPU Math** | PyTorch (CUDA 12.x Win wheel) | Ultra-fast VRAM-based blending, color matching, and export downscaling. |
| **Image I/O** | `opencv-python`, `Pillow`, `numpy` | Standard Windows pip wheels for basic image manipulation. |
| **Massive Canvas** | `tifffile`, `numpy.memmap` | The *only* safe, Windows-native way to handle 30k x 30k arrays without OOM crashes. |
| **Frontend** | React, Tailwind CSS, OpenSeadragon | Mission control UI, infinite deep-zoom rendering. |

---

## 6. Worked Examples (Math, Cost & Hybrid Benefit)

`base_tile_px = 2048`, `overlap = 25%`. Comparing pure-cloud tiling vs. cloud + local-2x-upscale hybrid:

| Target Canvas | Pure-Cloud Grid | Pure-Cloud Calls | Hybrid (2x Local Upscale) Grid | Hybrid Calls | Est. Cloud Cost |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 10,000 × 10,000 (1:1) | 7×7 | 49 | 4×4 | 16 | ~$0.42 |
| 12,000 × 8,000 (3:2) | 8×5 | 40 | 5×3 | 15 | ~$0.39 |
| 21,300 × 6,000 (32:9) | 14×4 | 56 | 8×2 | 16 | ~$0.42 |
| 16,000 × 9,000 (16:9) | 10×5 | 50 | 6×3 | 18 | ~$0.47 |

*(Cost ≈ tiles × $0.026. The hybrid approach roughly **3x reduces cloud call count**, buying back wall-clock time and rate-limit headroom, while providing local inpainting that materially improves seam quality.)*

---

## 7. Phased Delivery & Cursor Implementation Directives

When building in Cursor, follow this exact sequence to prevent context-overload and ensure stable module integration.

### Step 1: Data Models & Grid Math
> **Prompt Cursor:** "Create a Python module `grid_math.py`. It should take `target_width`, `target_height`, `base_tile_size` (2048), `upscale_factor` (2), and `overlap_fraction` (0.25). Calculate required rows/cols, stride, and generate a dependency graph dictionary where keys are `(r,c)` tuples and values are lists of required neighbor tuples. Include a `CanvasFormat` Pydantic model."

### Step 2: The xAI Adapter (Strict Rules)
> **Prompt Cursor:** "Create an async xAI API adapter class `XAIImageEngine`. It must have a `generate_blueprint` method (using `/v1/images/generations`) and a `generate_tile` method (using `/v1/images/edits`). **CRITICAL RULES:** The tile method MUST accept exactly 3 image paths (blueprint crop, left neighbor, top neighbor). If a neighbor doesn't exist, pass a solid black 512x512 placeholder image so we ALWAYS send >= 2 images to prevent the xAI AR-lock bug. Implement exponential backoff for HTTP 429 errors. Save returned images to a local `/tiles` folder immediately."

### Step 3: Wavefront Scheduler & WebSockets
> **Prompt Cursor:** "Create an async FastAPI router `mosaic_router.py`. Using the graph from `grid_math.py` and the `XAIImageEngine`, implement a wavefront scheduler. Process tiles in anti-diagonals concurrently. Update an in-memory state dict mapping tile IDs to statuses. Create a WebSocket endpoint `/ws/progress` that broadcasts this state dict to the frontend whenever a tile status changes."

### Step 4: ComfyUI Local Integration
> **Prompt Cursor:** "Create a class `LocalRTX4080Service`. It should communicate with a local ComfyUI instance on `localhost:8188`. Create a method `process_tile(tile_path)` that sends a predefined ComfyUI JSON workflow to the API. The workflow should take an input image, upscale it 2x using a basic ESRGAN node, run an SDXL inpaint node over the edge seams using a generated mask, and return the path to the final processed tile." *(Note: Build the inpainting workflow in ComfyUI UI first, export as JSON, and paste into Cursor here).*

### Step 5: The Memmap Compositor
> **Prompt Cursor:** "Create a class `CanvasCompositor`. It must use `numpy.memmap` to create a massive empty RGB array on disk matching target W/H. Create a method `stitch_tile(tile_path, r, c)` that uses PyTorch CUDA to perform linear gradient alpha blending in the overlap zones against neighboring pixels already in the memmap, writing the final pixels directly back into the memmap. Finally, use the `tifffile` library to save the memmap as a pyramidal BigTIFF."

### Step 6: Frontend Scaffolding & Mission Control
> **Prompt Cursor:** "Create a React component layout for 'Tessera' using Tailwind. 1. Left sidebar (300px) with the Blueprint Studio (AI Generate/Upload toggle, prompt box, AR dropdown, Lock button). 2. Main central viewport initializing OpenSeadragon. 3. Bottom-right fixed mini-map overlay (200x200px) that connects to the `/ws/progress` WebSocket and renders a CSS grid, coloring cells based on tile status (Gray, Blue, Orange, Green, Red). Update the OpenSeadragon viewer dynamically when a tile status turns Green."

### Step 7: The Export Bay
> **Prompt Cursor:** "Create a React modal 'ExportBay'. Two columns of checkboxes: Formats (JPEG with quality slider, PNG, WebP) and Sizes (Original, 8K, 4K, 1080p, Custom WxH maintaining aspect ratio). On submit, POST the matrix to a FastAPI `/api/export` endpoint. On the backend, implement the export endpoint to load the BigTIFF memmap into PyTorch, use `torch.nn.functional.interpolate` to downscale to requested sizes on the RTX 4080, encode via cv2.imencode, zip the results, and stream the zip to the frontend."