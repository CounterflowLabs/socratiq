"""Tests for TeachingAssetPlanner."""

from app.services.teaching_asset_planner import TeachingAssetPlanner


def test_planner_uses_no_lab_for_non_coding_material():
    planner = TeachingAssetPlanner()

    result = planner.plan(
        source_title="World History Overview",
        source_type="video",
        overall_summary="A survey of major historical events and themes.",
        chunk_topics=["history", "events", "themes"],
        has_code=False,
    )

    assert result.lab_mode == "none"
    assert result.graph_mode == "inline_and_overview"
    assert result.study_surface == "reader"


def test_planner_uses_inline_lab_for_coding_material():
    planner = TeachingAssetPlanner()

    result = planner.plan(
        source_title="Python Training Loop Walkthrough",
        source_type="video",
        overall_summary="A lesson about building a training loop.",
        chunk_topics=["model", "training loop", "optimization"],
        has_code=True,
    )

    assert result.lab_mode == "inline"
    assert result.graph_mode == "inline_and_overview"
    assert result.study_surface == "reader"
