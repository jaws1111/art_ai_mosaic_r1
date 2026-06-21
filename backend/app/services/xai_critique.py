"""Optional xAI vision critique for mosaic fidelity (token-limited)."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from app.core.config import Settings
from app.services.image_utils import image_to_data_url

logger = logging.getLogger(__name__)

CRITIQUE_PROMPT = """You are a strict quality auditor for AI image mosaics. Be precise and unforgiving.

Image 1 (side-by-side): LEFT = 2K blueprint (the reference). RIGHT = final mosaic output.
Image 2 (if present): blueprint edge outlines overlaid on mosaic in cyan — misalignment shows as gaps.

SCORING RULES (start at 100, subtract penalties):
- Subject changes apparent zoom/scale level compared to blueprint: -30 to -50
- A tile shows a different section of the scene OR repeats the full scene inside one tile: -40
- Major compositional element (building, figure, landscape feature) moved, missing, or added: -20 each
- Tile seam artifacts visible (edges, hard cuts, brightness jumps between panels): -15 each
- Perspective or camera angle notably different from blueprint: -25
- Scene crops tighter or wider than blueprint (different zoom): -20
- Detail added without composition change: +0 (expected, no bonus)
- Fine surface detail enhancement only: neutral

AUTOMATIC FAIL if ANY of:
- SCORE drops below 55
- Any tile clearly shows the full wide scene (not just its local section)
- Subject scale differs more than ~15% from blueprint

Reply in EXACTLY this structure:
SCORE: [0-100]
SCALE: [match / zoom-in / zoom-out / inconsistent — one word]
STRUCTURE: [one sentence — what changed in composition vs blueprint]
DETAIL: [one sentence — what detail was added or lost]
ISSUES:
- [specific issue or "none"]
VERDICT: [pass / fail]"""


async def request_mosaic_critique(
    settings: Settings,
    side_by_side_path: Path,
    outline_path: Path | None = None,
    *,
    max_output_tokens: int = 600,
) -> str:
    if not settings.xai_api_key:
        raise RuntimeError("XAI_API_KEY required for AI critique")

    content: list[dict] = [
        {
            "type": "input_image",
            "image_url": image_to_data_url(side_by_side_path),
            "detail": "low",
        },
    ]
    if outline_path and outline_path.is_file():
        content.append(
            {
                "type": "input_image",
                "image_url": image_to_data_url(outline_path),
                "detail": "low",
            }
        )
    content.append({"type": "input_text", "text": CRITIQUE_PROMPT})

    payload = {
        "model": settings.xai_critique_model,
        "input": [{"role": "user", "content": content}],
        "max_output_tokens": max_output_tokens,
        "store": False,
    }

    url = f"{settings.xai_base_url}/responses"
    headers = {
        "Authorization": f"Bearer {settings.xai_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            logger.warning("xAI critique failed: %s", response.text[:500])
            raise RuntimeError(f"xAI critique HTTP {response.status_code}")
        data = response.json()

    text = _extract_response_text(data)
    if not text:
        raise RuntimeError("Empty critique response from xAI")
    return text.strip()


def _extract_response_text(data: dict) -> str:
    if "output_text" in data and isinstance(data["output_text"], str):
        return data["output_text"]
    output = data.get("output") or []
    parts: list[str] = []
    for item in output:
        if item.get("type") == "message":
            for block in item.get("content") or []:
                if block.get("type") in ("output_text", "text"):
                    parts.append(block.get("text") or "")
    return "\n".join(p for p in parts if p)
