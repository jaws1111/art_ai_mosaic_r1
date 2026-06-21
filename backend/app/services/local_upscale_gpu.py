"""PyTorch CUDA tile upscaler — Stage 3 refinery, no ComfyUI required."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageFilter

from app.services.image_utils import ensure_rgb_image, save_rgb_image

logger = logging.getLogger(__name__)

_CUDA_AVAILABLE: bool | None = None
_DEVICE: str = "cpu"


def _init_cuda() -> bool:
    global _CUDA_AVAILABLE, _DEVICE
    if _CUDA_AVAILABLE is not None:
        return _CUDA_AVAILABLE
    try:
        import torch
        if torch.cuda.is_available():
            _DEVICE = "cuda"
            _CUDA_AVAILABLE = True
            logger.info("GPU upscaler: RTX CUDA available — %s", torch.cuda.get_device_name(0))
        else:
            _CUDA_AVAILABLE = False
            logger.info("GPU upscaler: CUDA not available, will use enhanced CPU path")
    except ImportError:
        _CUDA_AVAILABLE = False
        logger.info("GPU upscaler: torch not installed, using CPU path")
    return _CUDA_AVAILABLE


def cuda_available() -> bool:
    return _init_cuda()


def upscale_tile_gpu(
    input_path: Path,
    output_path: Path,
    target_px: int,
    *,
    sharpen: bool = True,
    sharpen_radius: float = 1.5,
    sharpen_amount: float = 90,
) -> Path:
    """
    Upscale tile to target_px using CUDA bicubic if available, else high-quality CPU.

    Returns output_path on success.
    """
    _init_cuda()

    if _CUDA_AVAILABLE:
        return _upscale_cuda(input_path, output_path, target_px, sharpen=sharpen)
    return _upscale_cpu_enhanced(
        input_path, output_path, target_px,
        sharpen=sharpen, radius=sharpen_radius, amount=sharpen_amount,
    )


def _upscale_cuda(
    input_path: Path,
    output_path: Path,
    target_px: int,
    *,
    sharpen: bool = True,
) -> Path:
    import torch
    import torch.nn.functional as F

    image = ensure_rgb_image(input_path)
    w, h = image.size
    if w == target_px and h == target_px and not sharpen:
        return save_rgb_image(image, output_path)

    import numpy as np
    arr = np.asarray(image, dtype=np.float32) / 255.0
    tensor = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).to(_DEVICE)

    if w != target_px or h != target_px:
        tensor = F.interpolate(
            tensor,
            size=(target_px, target_px),
            mode="bicubic",
            align_corners=False,
            antialias=True,
        )

    if sharpen:
        kernel = torch.tensor(
            [[[[0, -0.5, 0], [-0.5, 3, -0.5], [0, -0.5, 0]]]],
            dtype=torch.float32,
            device=_DEVICE,
        ).expand(3, 1, 3, 3)
        sharpened = torch.nn.functional.conv2d(
            tensor, kernel, padding=1, groups=3
        )
        tensor = torch.clamp(tensor * 0.85 + sharpened * 0.15, 0, 1)

    out_arr = tensor.squeeze(0).permute(1, 2, 0).cpu().numpy()
    out_img = Image.fromarray((out_arr * 255).clip(0, 255).astype("uint8"), "RGB")
    return save_rgb_image(out_img, output_path)


def _upscale_cpu_enhanced(
    input_path: Path,
    output_path: Path,
    target_px: int,
    *,
    sharpen: bool = True,
    radius: float = 1.5,
    amount: float = 90,
) -> Path:
    """High-quality CPU upscale: Lanczos + UnsharpMask."""
    image = ensure_rgb_image(input_path)
    w, h = image.size
    if w < target_px or h < target_px:
        if sharpen:
            image = image.filter(ImageFilter.UnsharpMask(radius=radius, percent=int(amount), threshold=2))
    resized = image.resize((target_px, target_px), Image.Resampling.LANCZOS)
    if sharpen and (w < target_px or h < target_px):
        resized = resized.filter(ImageFilter.UnsharpMask(radius=0.8, percent=40, threshold=1))
    return save_rgb_image(resized, output_path)
