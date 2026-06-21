"""Tests for blueprint vs mosaic quality assessment."""

from pathlib import Path

from PIL import Image

from app.services.image_utils import save_rgb_image
from app.services.quality_assessment import compute_metrics, generate_comparison_artifacts


def test_identical_images_score_high(tmp_path: Path):
    path = tmp_path / "same.png"
    save_rgb_image(Image.new("RGB", (256, 256), color=(80, 100, 120)), path)
    bp = Image.open(path)
    ms = Image.open(path)
    metrics, _, _ = compute_metrics(bp, ms, max_px=512)
    assert metrics.ssim > 0.99
    assert metrics.passed


def test_comparison_artifacts_created(tmp_path: Path):
    bp = tmp_path / "bp.png"
    ms = tmp_path / "ms.png"
    save_rgb_image(Image.new("RGB", (128, 128), color=(0, 0, 0)), bp)
    save_rgb_image(Image.new("RGB", (128, 128), color=(255, 255, 255)), ms)
    out = tmp_path / "quality"
    metrics, artifacts = generate_comparison_artifacts(bp, ms, out, max_px=256)
    assert metrics.passed is False
    assert "side_by_side" in artifacts
    assert artifacts["side_by_side"].is_file()
