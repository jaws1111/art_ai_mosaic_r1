from pathlib import Path

from app.core.storage import RunPaths, coord_label, seq_label


def test_run_paths_layout(tmp_path: Path):
    paths = RunPaths.create(tmp_path, "phase0_test")
    paths.ensure_all()

    assert paths.blueprint_path().name == "01_blueprint.png"
    assert paths.tile_path(1, 0, 0).name == "001_tile_r0-c0.png"
    assert paths.ref_blueprint_crop_path(2, 1, 0).name == "002_ref_blueprint_crop_r1-c0.png"
    assert paths.final_feather_blend_path().name == "02_mosaic_feather_blend.png"


def test_coord_and_seq_labels():
    assert coord_label(1, 2) == "r1-c2"
    assert seq_label(7) == "007"
