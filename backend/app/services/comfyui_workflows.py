"""Programmatic ComfyUI workflow builders for Tessera local refinery."""

from __future__ import annotations


def upscale_workflow(
    uploaded_filename: str,
    *,
    model_name: str = "RealESRGAN_x4plus.pth",
    filename_prefix: str = "tessera_upscale",
) -> dict:
    """
    Real-ESRGAN upscale via ComfyUI UpscaleModelLoader.

    Requires `ComfyUI-Upscaler` / built-in upscale nodes and model in models/upscale_models/.
    """
    return {
        "1": {
            "class_type": "LoadImage",
            "inputs": {"image": uploaded_filename},
        },
        "2": {
            "class_type": "UpscaleModelLoader",
            "inputs": {"model_name": model_name},
        },
        "3": {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]},
        },
        "4": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": filename_prefix, "images": ["3", 0]},
        },
    }


def resize_workflow(
    uploaded_filename: str,
    width: int,
    height: int,
    *,
    filename_prefix: str = "tessera_resize",
) -> dict:
    """Exact resize after upscale when model factor != target factor."""
    return {
        "1": {
            "class_type": "LoadImage",
            "inputs": {"image": uploaded_filename},
        },
        "2": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["1", 0],
                "width": width,
                "height": height,
                "upscale_method": "lanczos",
                "crop": "disabled",
            },
        },
        "3": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": filename_prefix, "images": ["2", 0]},
        },
    }
