"""Run-scoped and project-wide image storage paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def coord_label(row: int, col: int) -> str:
    return f"r{row}-c{col}"


def seq_label(sequence: int, width: int = 3) -> str:
    return str(sequence).zfill(width)


@dataclass(frozen=True)
class RunPaths:
    """
    Logical layout for one generation run:

    data/runs/{run_id}/
      manifest.json
      blueprint/01_blueprint.png
      working/tiles/001_tile_r0-c0.png
      working/refs/001_ref_blueprint_crop_r0-c0.png
      final/01_mosaic_hard_paste.png
    """

    run_id: str
    root: Path

    @classmethod
    def create(cls, runs_dir: Path, run_id: str) -> RunPaths:
        return cls(run_id=run_id, root=runs_dir / run_id)

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @property
    def blueprint_dir(self) -> Path:
        return self.root / "blueprint"

    @property
    def working_dir(self) -> Path:
        return self.root / "working"

    @property
    def working_tiles_dir(self) -> Path:
        return self.working_dir / "tiles"

    @property
    def working_refs_dir(self) -> Path:
        return self.working_dir / "refs"

    @property
    def working_processed_dir(self) -> Path:
        return self.working_dir / "processed"

    @property
    def final_dir(self) -> Path:
        return self.root / "final"

    def blueprint_path(self) -> Path:
        return self.blueprint_dir / "01_blueprint.png"

    def tile_path(self, sequence: int, row: int, col: int) -> Path:
        label = coord_label(row, col)
        return self.working_tiles_dir / f"{seq_label(sequence)}_tile_{label}.png"

    def ref_blueprint_crop_path(self, sequence: int, row: int, col: int) -> Path:
        label = coord_label(row, col)
        return self.working_refs_dir / f"{seq_label(sequence)}_ref_blueprint_crop_{label}.png"

    def blueprint_crop_stable_path(self, row: int, col: int) -> Path:
        """Stable path for the blueprint crop keyed only by (row, col).

        Used so neighbouring tiles can look up the crop without knowing the seq number.
        """
        label = coord_label(row, col)
        return self.working_refs_dir / f"blueprint_crop_{label}.png"

    def ref_left_strip_path(self, sequence: int, row: int, col: int) -> Path:
        label = coord_label(row, col)
        return self.working_refs_dir / f"{seq_label(sequence)}_ref_left_strip_{label}.png"

    def ref_top_strip_path(self, sequence: int, row: int, col: int) -> Path:
        label = coord_label(row, col)
        return self.working_refs_dir / f"{seq_label(sequence)}_ref_top_strip_{label}.png"

    def final_hard_paste_path(self) -> Path:
        return self.final_dir / "01_mosaic_hard_paste.png"

    def final_feather_blend_path(self) -> Path:
        return self.final_dir / "02_mosaic_feather_blend.png"

    def final_comparison_path(self) -> Path:
        return self.final_dir / "03_comparison_hard_vs_feather.png"

    def dzi_dir(self) -> Path:
        return self.final_dir / "dzi"

    def dzi_descriptor_path(self, name: str = "mosaic") -> Path:
        return self.dzi_dir() / f"{name}.dzi"

    def processed_tile_path(self, sequence: int, row: int, col: int) -> Path:
        label = coord_label(row, col)
        return self.working_processed_dir / f"{seq_label(sequence)}_processed_{label}.png"

    def ensure_all(self) -> None:
        for path in (
            self.root,
            self.blueprint_dir,
            self.working_tiles_dir,
            self.working_refs_dir,
            self.working_processed_dir,
            self.final_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def ensure_dzi_dir(self) -> Path:
        self.dzi_dir().mkdir(parents=True, exist_ok=True)
        return self.dzi_dir()

    def relative(self, path: Path, base: Path) -> str:
        try:
            return str(path.relative_to(base))
        except ValueError:
            return str(path)
