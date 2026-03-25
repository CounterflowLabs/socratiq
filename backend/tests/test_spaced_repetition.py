"""Tests for SM-2 spaced repetition algorithm."""

import pytest


class TestSM2Algorithm:
    def test_first_rep_interval_1(self):
        from app.services.spaced_repetition import SpacedRepetitionService
        svc = SpacedRepetitionService()
        e, i, r = svc.calculate(quality=5, easiness=2.5, interval_days=1, repetitions=0)
        assert i == 1
        assert r == 1

    def test_second_rep_interval_6(self):
        from app.services.spaced_repetition import SpacedRepetitionService
        svc = SpacedRepetitionService()
        e, i, r = svc.calculate(quality=4, easiness=2.5, interval_days=1, repetitions=1)
        assert i == 6
        assert r == 2

    def test_third_rep_uses_easiness(self):
        from app.services.spaced_repetition import SpacedRepetitionService
        svc = SpacedRepetitionService()
        e, i, r = svc.calculate(quality=4, easiness=2.5, interval_days=6, repetitions=2)
        assert i == round(6 * e)  # interval = prev * new_easiness
        assert r == 3

    def test_failed_recall_resets(self):
        from app.services.spaced_repetition import SpacedRepetitionService
        svc = SpacedRepetitionService()
        e, i, r = svc.calculate(quality=1, easiness=2.5, interval_days=15, repetitions=5)
        assert i == 1
        assert r == 0

    def test_easiness_never_below_1_3(self):
        from app.services.spaced_repetition import SpacedRepetitionService
        svc = SpacedRepetitionService()
        e, i, r = svc.calculate(quality=0, easiness=1.3, interval_days=1, repetitions=0)
        assert e == 1.3

    def test_quality_3_passes(self):
        from app.services.spaced_repetition import SpacedRepetitionService
        svc = SpacedRepetitionService()
        _, i, r = svc.calculate(quality=3, easiness=2.5, interval_days=1, repetitions=0)
        assert r == 1

    def test_quality_2_fails(self):
        from app.services.spaced_repetition import SpacedRepetitionService
        svc = SpacedRepetitionService()
        _, i, r = svc.calculate(quality=2, easiness=2.5, interval_days=6, repetitions=3)
        assert r == 0
        assert i == 1
