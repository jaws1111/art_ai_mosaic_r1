"""Async xAI Imagine API adapter — outpainting strategy with neighbor-first references."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from PIL import Image

from app.core.config import Settings
from app.services.image_utils import ensure_placeholder_file, ensure_rgb_image, image_to_data_url, save_rgb_image

logger = logging.getLogger(__name__)

XAIEventHook = Callable[[str, str], Awaitable[None]]


class XAIRateLimitError(Exception):
    """Raised when xAI returns HTTP 429."""


class XAIAPIError(Exception):
    """Raised for non-retryable xAI API failures."""


class XAIImageEngine:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        on_event: XAIEventHook | None = None,
    ) -> None:
        self.settings = settings
        self._client = client
        self._owns_client = client is None
        self.placeholder_path = settings.placeholder_path
        self.on_event = on_event

    async def _notify(self, action: str, detail: str) -> None:
        if self.on_event:
            await self.on_event(action, detail)

    async def __aenter__(self) -> XAIImageEngine:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0))
        ensure_placeholder_file(self.placeholder_path, self.settings.placeholder_size)
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("XAIImageEngine must be used as an async context manager.")
        return self._client

    def _headers(self) -> dict[str, str]:
        if not self.settings.xai_api_key:
            raise XAIAPIError("XAI_API_KEY is missing. Copy .env.example to .env and set your key.")
        return {
            "Authorization": f"Bearer {self.settings.xai_api_key}",
            "Content-Type": "application/json",
        }

    async def _request_json(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.settings.xai_base_url}{path}"
        await self._notify("request", f"{method} {path}")
        response = await self.client.request(method, url, headers=self._headers(), json=payload)
        if response.status_code == 429:
            await self._notify("rate_limit", f"429 on {path} — backing off")
            raise XAIRateLimitError(response.text)
        if response.status_code >= 400:
            await self._notify("error", f"HTTP {response.status_code} on {path}")
            raise XAIAPIError(f"xAI API error {response.status_code}: {response.text}")
        await self._notify("response", f"{response.status_code} {path}")
        return response.json()

    async def _with_backoff(self, operation: str, coro_factory: Any, max_retries: int = 6) -> dict[str, Any]:
        delay = 1.0
        for attempt in range(max_retries):
            try:
                return await coro_factory()
            except XAIRateLimitError as exc:
                if attempt == max_retries - 1:
                    raise
                logger.warning("%s hit rate limit; retrying in %.1fs (%s)", operation, delay, exc)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60.0)
        raise XAIAPIError(f"{operation} failed after retries.")

    async def _download_image(self, url: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        await self._notify("download", f"Fetching image → {output_path.name}")
        try:
            response = await self.client.get(url)
            if response.status_code >= 400:
                raise XAIAPIError(f"Failed to download generated image: {response.status_code}")
            output_path.write_bytes(response.content)
            return output_path
        finally:
            await self._notify("download_done", output_path.name)

    def _extract_image_url(self, payload: dict[str, Any]) -> str:
        data = payload.get("data") or []
        if not data:
            raise XAIAPIError(f"No image data in xAI response: {payload}")
        url = data[0].get("url")
        if not url:
            raise XAIAPIError(f"No image URL in xAI response: {payload}")
        return url

    async def generate_blueprint(
        self,
        prompt: str,
        output_path: Path,
        aspect_ratio: str = "1:1",
        resolution: str = "2k",
    ) -> Path:
        payload = {
            "model": self.settings.xai_model,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "n": 1,
        }

        async def call() -> dict[str, Any]:
            await self._notify("blueprint", f"Generating 2K blueprint ({aspect_ratio})")
            return await self._request_json("POST", "/images/generations", payload)

        result = await self._with_backoff("generate_blueprint", call)
        image_url = self._extract_image_url(result)
        saved = await self._download_image(image_url, output_path)
        logger.info("Saved blueprint to %s", saved)
        return saved

    def _image_ref(self, path: Path) -> dict[str, str]:
        return {"url": image_to_data_url(path), "type": "image_url"}

    def _resized_ref(self, path: Path, max_px: int = 1024) -> dict[str, str]:
        """Return an image_ref with the image resized to at most max_px on the long edge."""
        img = ensure_rgb_image(path)
        w, h = img.size
        if max(w, h) > max_px:
            scale = max_px / max(w, h)
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp = Path(f.name)
        save_rgb_image(img, tmp)
        try:
            ref = self._image_ref(tmp)
        finally:
            tmp.unlink(missing_ok=True)
        return ref

    async def generate_tile(
        self,
        prompt: str,
        blueprint_crop_path: Path,
        left_neighbor_path: Path | None,
        top_neighbor_path: Path | None,
        output_path: Path,
        aspect_ratio: str = "1:1",
        resolution: str = "2k",
    ) -> Path:
        """
        Outpainting strategy:
          - Neighbors (full tiles resized to 1024px) are IMAGE_0 / IMAGE_1 — primary context.
          - Blueprint crop is IMAGE_2 — content/style guide.
        When no neighbors exist (first tile) the blueprint crop is the sole reference.
        """
        images: list[dict[str, str]] = []

        if left_neighbor_path and left_neighbor_path.is_file():
            images.append(self._resized_ref(left_neighbor_path))
        if top_neighbor_path and top_neighbor_path.is_file():
            images.append(self._resized_ref(top_neighbor_path))

        # Blueprint crop fills the remaining slots (always include)
        images.append(self._resized_ref(blueprint_crop_path, max_px=2048))

        # xAI edits endpoint requires exactly 3 images
        while len(images) < 3:
            images.append(self._image_ref(self.placeholder_path))

        payload = {
            "model": self.settings.xai_model,
            "prompt": prompt,
            "images": images[:3],
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "n": 1,
        }

        async def call() -> dict[str, Any]:
            await self._notify("tile", f"Generating tile → {output_path.name}")
            return await self._request_json("POST", "/images/edits", payload)

        result = await self._with_backoff("generate_tile", call)
        image_url = self._extract_image_url(result)
        saved = await self._download_image(image_url, output_path)
        logger.info("Saved tile to %s", saved)
        return saved
