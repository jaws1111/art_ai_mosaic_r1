"""Tests for regional prompt resolution."""

from app.models.regions import PromptRegion
from app.services.region_prompts import (
    build_blueprint_prompt,
    region_coverages,
    resolve_tile_content,
)


def test_single_region_covers_tile():
    regions = [
        PromptRegion(
            id="a",
            prompt="Snowy mountains",
            x=0.0,
            y=0.0,
            w=0.5,
            h=1.0,
        )
    ]
    coverages = region_coverages(0, 0, 2, 2, regions)
    assert len(coverages) == 1
    assert coverages[0][1] == 1.0
    assert resolve_tile_content("master", regions, 0, 0, 2, 2) == "Snowy mountains"


def test_straddling_tile_gets_transition():
    regions = [
        PromptRegion(id="left", prompt="Forest", x=0.0, y=0.0, w=0.5, h=1.0),
        PromptRegion(id="right", prompt="City", x=0.5, y=0.0, w=0.5, h=1.0),
    ]
    content = resolve_tile_content("master", regions, 0, 1, 1, 3)
    assert "Transition" in content
    assert "Forest" in content
    assert "City" in content


def test_blueprint_prompt_lists_zones():
    regions = [
        PromptRegion(id="a", label="North", prompt="Peaks", x=0.0, y=0.0, w=1.0, h=0.5),
    ]
    prompt = build_blueprint_prompt("Style.", "Master scene.", regions)
    assert "North" in prompt
    assert "Peaks" in prompt
