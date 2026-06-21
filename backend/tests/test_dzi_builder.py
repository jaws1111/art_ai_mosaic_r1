"""Tests for DZI pyramid builder."""

from pathlib import Path

from PIL import Image

from app.services.dzi_builder import build_dzi


def test_build_dzi_creates_descriptor_and_tiles(tmp_path: Path):
    source = tmp_path / "source.png"
    Image.new("RGB", (512, 256), color=(128, 64, 32)).save(source)

    dzi_dir = tmp_path / "dzi"
    dzi_path = build_dzi(source, dzi_dir, name="mosaic")

    assert dzi_path.is_file()
    assert "Width=\"512\"" in dzi_path.read_text(encoding="utf-8")
    tiles_dir = dzi_dir / "mosaic_files"
    assert tiles_dir.is_dir()
    assert any(tiles_dir.rglob("*.jpg"))
