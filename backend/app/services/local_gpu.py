"""ComfyUI local GPU service (Phase 1.4)."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image

from app.core.config import Settings
from app.services.comfyui_workflows import resize_workflow, upscale_workflow
from app.services.local_refinery import upscale_tile_lanczos

logger = logging.getLogger(__name__)


class LocalRTX4080Service:
    """HTTP client for headless ComfyUI on localhost:8188."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.comfyui_url

    async def is_available(self) -> bool:
        if not self.settings.comfyui_enabled:
            return False
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
                response = await client.get(f"{self.base_url}/system_stats")
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def upload_image(self, image_path: Path) -> str | None:
        """Upload a PNG to ComfyUI input folder; returns server-side filename."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                with image_path.open("rb") as handle:
                    response = await client.post(
                        f"{self.base_url}/upload/image",
                        files={"image": (image_path.name, handle, "image/png")},
                        data={"overwrite": "true"},
                    )
                if response.status_code >= 400:
                    logger.error("ComfyUI upload failed: %s", response.text)
                    return None
                data = response.json()
                return data.get("name")
        except httpx.HTTPError as exc:
            logger.warning("ComfyUI upload error: %s", exc)
            return None

    async def submit_workflow(self, workflow_json: dict) -> str | None:
        payload = {"prompt": workflow_json, "client_id": uuid.uuid4().hex}
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            response = await client.post(f"{self.base_url}/prompt", json=payload)
            if response.status_code >= 400:
                logger.error("ComfyUI queue failed: %s", response.text)
                return None
            return response.json().get("prompt_id")

    async def wait_for_prompt(self, prompt_id: str, timeout_s: float = 300.0) -> dict | None:
        deadline = time.monotonic() + timeout_s
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            while time.monotonic() < deadline:
                response = await client.get(f"{self.base_url}/history/{prompt_id}")
                if response.status_code >= 400:
                    await asyncio.sleep(1.0)
                    continue
                history = response.json()
                if prompt_id in history:
                    return history[prompt_id]
                await asyncio.sleep(0.75)
        logger.error("ComfyUI prompt %s timed out", prompt_id)
        return None

    def _extract_output_image(self, history_entry: dict) -> tuple[str, str, str] | None:
        outputs = history_entry.get("outputs") or {}
        for node_output in outputs.values():
            images = node_output.get("images") or []
            if images:
                img = images[0]
                return img.get("filename", ""), img.get("subfolder", ""), img.get("type", "output")
        return None

    async def download_output(
        self,
        filename: str,
        subfolder: str,
        output_type: str,
        dest_path: Path,
    ) -> bool:
        params = {"filename": filename, "subfolder": subfolder, "type": output_type}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                response = await client.get(f"{self.base_url}/view", params=params)
                if response.status_code >= 400:
                    return False
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path.write_bytes(response.content)
                return True
        except httpx.HTTPError as exc:
            logger.warning("ComfyUI download error: %s", exc)
            return False

    async def upscale_tile(
        self,
        input_path: Path,
        output_path: Path,
        target_px: int,
    ) -> bool:
        """
        Upscale via Real-ESRGAN, then resize to exact target_px if model factor differs.

        Falls back to False so caller can use Lanczos.
        """
        if not await self.is_available():
            return False

        uploaded = await self.upload_image(input_path)
        if not uploaded:
            return False

        workflow = upscale_workflow(
            uploaded,
            model_name=self.settings.comfyui_upscale_model,
            filename_prefix=f"tessera_{uuid.uuid4().hex[:8]}",
        )
        prompt_id = await self.submit_workflow(workflow)
        if not prompt_id:
            return False

        history = await self.wait_for_prompt(prompt_id)
        if not history:
            return False

        image_meta = self._extract_output_image(history)
        if not image_meta:
            return False

        temp_path = output_path.with_suffix(".comfy.png")
        if not await self.download_output(*image_meta, temp_path):
            return False

        upscaled = temp_path
        with Image.open(temp_path) as img:
            current_px = max(img.width, img.height)
        if current_px != target_px:
            resized_upload = await self.upload_image(temp_path)
            if resized_upload:
                resize_wf = resize_workflow(
                    resized_upload,
                    target_px,
                    target_px,
                    filename_prefix=f"tessera_fit_{uuid.uuid4().hex[:8]}",
                )
                resize_id = await self.submit_workflow(resize_wf)
                if resize_id:
                    resize_history = await self.wait_for_prompt(resize_id)
                    if resize_history:
                        resize_meta = self._extract_output_image(resize_history)
                        if resize_meta and await self.download_output(*resize_meta, output_path):
                            temp_path.unlink(missing_ok=True)
                            return True

        if current_px == target_px:
            temp_path.rename(output_path)
            return True

        upscale_tile_lanczos(temp_path, output_path, target_px, sharpen=False)
        temp_path.unlink(missing_ok=True)
        return True

    async def inpaint_seam(self, left_tile: Path, right_tile: Path, output_path: Path) -> bool:
        """Reserved for SDXL+ControlNet workflow export (Phase 2)."""
        logger.info("ComfyUI seam inpaint pending full workflow — using CPU harmonization")
        return False


async def is_comfyui_available(settings: Settings) -> bool:
    return await LocalRTX4080Service(settings).is_available()
