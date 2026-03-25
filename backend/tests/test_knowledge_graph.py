"""Tests for knowledge graph service."""

import pytest
from app.services.knowledge_graph import KnowledgeGraphService


class TestMasteryCalculation:
    def test_no_data_returns_zero(self):
        mastery = KnowledgeGraphService.calculate_mastery_score(
            review_easiness=None, exercise_scores=[]
        )
        assert mastery == 0.0

    def test_review_only(self):
        mastery = KnowledgeGraphService.calculate_mastery_score(
            review_easiness=2.5, exercise_scores=[]
        )
        assert mastery == pytest.approx(0.5 * 0.4, abs=0.01)  # 2.5/5 * 0.4

    def test_exercise_only(self):
        mastery = KnowledgeGraphService.calculate_mastery_score(
            review_easiness=None, exercise_scores=[80.0, 100.0]
        )
        assert mastery == pytest.approx(0.9 * 0.6, abs=0.01)  # avg(80,100)/100 * 0.6

    def test_both(self):
        mastery = KnowledgeGraphService.calculate_mastery_score(
            review_easiness=3.0, exercise_scores=[100.0]
        )
        expected = (3.0 / 5.0) * 0.4 + (100.0 / 100.0) * 0.6
        assert mastery == pytest.approx(expected, abs=0.01)
