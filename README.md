# Tessera — Multi-Megapixel Mosaic Engine

Generate seamless, coherent images exceeding **10,000×10,000 pixels** at arbitrary aspect ratios by orchestrating xAI `grok-imagine-image-quality` API tile generation with local RTX 4080 acceleration for upscaling, seam repair, and compositing.

## Overview

Tessera is a Windows 10 desktop/web-hybrid application that:

- Chains context-conditioned xAI image generations into a tiled mosaic
- Uses ComfyUI (headless) on an RTX 4080 for Real-ESRGAN upscaling and SDXL/FLUX seam inpainting
- Composites into pyramidal BigTIFF via streaming `numpy.memmap` (no full-RAM canvas)
- Presents a mission-control UI with live tile progress, deep-zoom preview, and GPU-accelerated export

## Documentation

| Document | Description |
|----------|-------------|
| [MASTER_PLAN.md](doc/MASTER_PLAN.md) | Consolidated architecture, phases, and implementation roadmap |
| [mosaic-image-engine-plan.md](doc/mosaic-image-engine-plan.md) | Original research & architecture plan |
| [STORAGE_ARCHITECTURE.md](doc/STORAGE_ARCHITECTURE.md) | Image folder layout (working vs final, sequencing) |

## Tech Stack

- **Backend:** Python 3.10+, FastAPI, asyncio wavefront scheduler, SQLite
- **Local GPU:** ComfyUI (Windows portable), PyTorch CUDA
- **Frontend:** React, Tailwind CSS, OpenSeadragon
- **Image I/O:** OpenCV, Pillow, tifffile, numpy.memmap

## Requirements

- Windows 10
- NVIDIA RTX 4080 (16GB VRAM recommended)
- xAI API key
- ComfyUI portable build with SDXL, ControlNet-Tile, Real-ESRGAN models

## Status

# Phase 1 — Core pipeline (in progress)

**Windows shortcuts** (project root):

| Script | Action |
|--------|--------|
| `launch.cmd` | Start API + Vite in separate windows |
| `status.cmd` | Show whether ports 8000 / 5522 are running |
| `stop-vite.cmd` | Stop Vite dev server (port 5522) |
| `stop-backend.cmd` | Stop FastAPI (port 8000) |

```powershell
# Or manually:
cd backend
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

API: http://127.0.0.1:8000 · UI: http://127.0.0.1:5522

See [STORAGE_ARCHITECTURE.md](doc/STORAGE_ARCHITECTURE.md) for image folder layout.

See [MASTER_PLAN.md](doc/MASTER_PLAN.md) for the full build sequence.

## License

TBD
