"""Celery app registration tests."""

from app.worker.celery_app import celery_app


def test_course_generation_task_is_registered() -> None:
    assert "course_generation.generate_course" in celery_app.tasks
