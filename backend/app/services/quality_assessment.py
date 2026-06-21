"""Blueprint vs mosaic fidelity assessment (Phase 3+).

Methodology:
- Downsample both to a common review resolution (max long edge configurable).
- SSIM / edge-overlap / gradient-detail ratio measure structure vs detail gain.
- Generate comparison PNGs: side-by-side, overlay, difference, outline, multiply.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from app.services.image_utils import ensure_rgb_image, save_rgb_image

logger = logging.getLogger(__name__)


@dataclass
class QualityMetrics:
    ssim: float
    edge_overlap: float
    mse: float
    detail_ratio: float
    overall_score: float
    passed: bool
    notes: list[str]


def _fit_long_edge(image: Image.Image, max_px: int) -> Image.Image:
    w, h = image.size
    long_edge = max(w, h)
    if long_edge <= max_px:
        return image
    scale = max_px / long_edge
    return image.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)


def _align_pair(blueprint: Image.Image, mosaic: Image.Image, max_px: int) -> tuple[Image.Image, Image.Image]:
    bp = blueprint
    ms = mosaic
    if ms.width > 0 and ms.height > 0 and bp.width > 0 and bp.height > 0:
        mosaic_ar = ms.width / ms.height
        blueprint_ar = bp.width / bp.height
        if abs(mosaic_ar - blueprint_ar) / mosaic_ar > 0.02:
            target_h = bp.height
            target_w = max(1, int(target_h * mosaic_ar))
            bp = bp.resize((target_w, target_h), Image.Resampling.LANCZOS)
    bp = _fit_long_edge(bp, max_px)
    ms = _fit_long_edge(ms, max_px)
    target = (min(bp.width, ms.width), min(bp.height, ms.height))
    if bp.size != target:
        bp = bp.resize(target, Image.Resampling.LANCZOS)
    if ms.size != target:
        ms = ms.resize(target, Image.Resampling.LANCZOS)
    return bp, ms


def _to_gray_array(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("L"), dtype=np.float32)


def _ssim_simple(a: np.ndarray, b: np.ndarray) -> float:
    """Windowless global SSIM approximation (fast, no extra deps)."""
    if a.size == 0 or b.size == 0:
        return 0.0
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    mu_a = a.mean()
    mu_b = b.mean()
    sigma_a = a.var()
    sigma_b = b.var()
    sigma_ab = float(((a - mu_a) * (b - mu_b)).mean())
    num = (2 * mu_a * mu_b + c1) * (2 * sigma_ab + c2)
    den = (mu_a**2 + mu_b**2 + c1) * (sigma_a + sigma_b + c2)
    return float(num / den) if den else 0.0


def _sobel_edges(gray: np.ndarray) -> np.ndarray:
    kx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float32)
    ky = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=np.float32)
    from numpy.lib.stride_tricks import sliding_window_view

    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return np.zeros_like(gray, dtype=bool)
    patches = sliding_window_view(gray, (3, 3))
    gx = (patches * kx).sum(axis=(-2, -1))
    gy = (patches * ky).sum(axis=(-2, -1))
    mag = np.hypot(gx, gy)
    threshold = float(np.percentile(mag, 90))
    padded = np.zeros_like(gray, dtype=bool)
    padded[1:-1, 1:-1] = mag >= threshold
    return padded


def _edge_overlap(a: np.ndarray, b: np.ndarray) -> float:
    ea = _sobel_edges(a)
    eb = _sobel_edges(b)
    inter = np.logical_and(ea, eb).sum()
    union = np.logical_or(ea, eb).sum()
    return float(inter / union) if union else 1.0


def _laplacian_variance(gray: np.ndarray) -> float:
    kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
    from numpy.lib.stride_tricks import sliding_window_view

    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return 0.0
    patches = sliding_window_view(gray, (3, 3))
    lap = (patches * kernel).sum(axis=(-2, -1))
    return float(lap.var())


def compute_metrics(blueprint: Image.Image, mosaic: Image.Image, max_px: int) -> tuple[QualityMetrics, Image.Image, Image.Image]:
    bp, ms = _align_pair(blueprint, mosaic, max_px)
    ga = _to_gray_array(bp)
    gb = _to_gray_array(ms)
    ssim = _ssim_simple(ga, gb)
    edge = _edge_overlap(ga, gb)
    mse = float(np.mean((ga - gb) ** 2))
    detail_bp = _laplacian_variance(ga)
    detail_ms = _laplacian_variance(gb)
    detail_ratio = detail_ms / detail_bp if detail_bp > 1e-6 else 1.0

    structure = ssim * 0.45 + edge * 0.35
    detail_bonus = min(max(detail_ratio - 1.0, 0.0), 1.0) * 0.15
    mse_penalty = min(mse / 2500.0, 1.0) * 0.05
    overall = max(0.0, min(100.0, (structure + detail_bonus - mse_penalty) * 100))

    notes: list[str] = []
    if ssim < 0.55:
        notes.append("Low structural similarity — layout may have drifted from blueprint.")
    if edge < 0.45:
        notes.append("Edge alignment weak — shapes/contours may have shifted.")
    if detail_ratio < 1.05:
        notes.append("Mosaic lacks expected detail gain over blueprint.")
    elif detail_ratio > 1.4:
        notes.append("Strong detail enhancement vs blueprint (expected for mosaic upscaling).")
    if mse > 1200:
        notes.append("Large tonal difference vs blueprint (may be intentional grading).")

    passed = ssim >= 0.55 and edge >= 0.42 and detail_ratio >= 0.95
    metrics = QualityMetrics(
        ssim=round(ssim, 4),
        edge_overlap=round(edge, 4),
        mse=round(mse, 2),
        detail_ratio=round(detail_ratio, 3),
        overall_score=round(overall, 1),
        passed=passed,
        notes=notes,
    )
    return metrics, bp, ms


def _side_by_side(left: Image.Image, right: Image.Image, gap: int = 8) -> Image.Image:
    h = max(left.height, right.height)
    canvas = Image.new("RGB", (left.width + right.width + gap, h), (16, 16, 16))
    canvas.paste(left, (0, 0))
    canvas.paste(right, (left.width + gap, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 8), "Blueprint", fill=(180, 180, 180))
    draw.text((left.width + gap + 8, 8), "Mosaic", fill=(180, 180, 180))
    return canvas


def _overlay_50(a: Image.Image, b: Image.Image) -> Image.Image:
    return Image.blend(a, b, alpha=0.5)


def _difference_amp(a: Image.Image, b: Image.Image, gain: float = 3.0) -> Image.Image:
    diff = ImageChops.difference(a, b)
    arr = np.clip(np.asarray(diff, dtype=np.float32) * gain, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, mode="RGB")


def _outline_overlay(base: Image.Image, blueprint: Image.Image) -> Image.Image:
    gray = _to_gray_array(blueprint)
    edges = _sobel_edges(gray)
    out = base.copy()
    draw = ImageDraw.Draw(out)
    ys, xs = np.where(edges)
    for y, x in zip(ys[::4], xs[::4], strict=False):
        draw.point((int(x), int(y)), fill=(0, 255, 255))
    return out


def _multiply_blend(a: Image.Image, b: Image.Image) -> Image.Image:
    return ImageChops.multiply(a, b)


def generate_comparison_artifacts(
    blueprint_path: Path,
    mosaic_path: Path,
    output_dir: Path,
    *,
    max_px: int = 2048,
) -> tuple[QualityMetrics, dict[str, Path]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    blueprint = ensure_rgb_image(blueprint_path)
    mosaic = ensure_rgb_image(mosaic_path)
    metrics, bp, ms = compute_metrics(blueprint, mosaic, max_px)

    artifacts: dict[str, Path] = {}
    mapping = {
        "side_by_side": _side_by_side(bp, ms),
        "overlay_50": _overlay_50(bp, ms),
        "difference": _difference_amp(bp, ms),
        "outline": _outline_overlay(ms, bp),
        "multiply": _multiply_blend(bp, ms),
    }
    for key, image in mapping.items():
        path = output_dir / f"compare_{key}.png"
        save_rgb_image(image, path)
        artifacts[key] = path

    logger.info(
        "Quality score %.1f SSIM=%.3f edge=%.3f detail=%.2fx",
        metrics.overall_score,
        metrics.ssim,
        metrics.edge_overlap,
        metrics.detail_ratio,
    )
    return metrics, artifacts
