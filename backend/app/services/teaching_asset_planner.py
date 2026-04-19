"""Lightweight planner for lesson teaching assets."""

import re

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

    _MARKER_PATTERNS = tuple(
        re.compile(rf"\b{re.escape(marker)}\b", re.IGNORECASE)
        for marker in _CODING_MARKERS
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
        lab_mode = "inline" if has_code or any(
            pattern.search(haystack) for pattern in self._MARKER_PATTERNS
        ) else "none"
        return TeachingAssetPlan(
            lab_mode=lab_mode,
            graph_mode="inline_and_overview",
        )
