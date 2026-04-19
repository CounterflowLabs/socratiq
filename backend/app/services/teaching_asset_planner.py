"""Lightweight planner for lesson teaching assets."""

from app.models.lesson_blocks import TeachingAssetPlan


class TeachingAssetPlanner:
    """Choose lesson surfaces with simple heuristics."""

    _CODING_MARKERS = (
        "python",
        "javascript",
        "training loop",
        "api",
        "tokenizer",
        "backpropagation",
    )

    def plan(
        self,
        source_title: str,
        source_type: str,
        overall_summary: str,
        chunk_topics: list[str],
        has_code: bool,
    ) -> TeachingAssetPlan:
        """Return a lightweight asset plan for the source."""

        del source_type
        haystack = " ".join([source_title, overall_summary, *chunk_topics]).lower()
        lab_mode = "inline" if has_code or any(marker in haystack for marker in self._CODING_MARKERS) else "none"
        return TeachingAssetPlan(
            lab_mode=lab_mode,
            graph_mode="inline_and_overview",
        )
