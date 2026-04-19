"""Database models package. Import all models here for Alembic metadata discovery."""

from app.db.models.base import Base, BaseMixin
from app.db.models.user import User
from app.db.models.source import Source
from app.db.models.source_task import SourceTask
from app.db.models.course import Course, CourseSource, Section
from app.db.models.concept import Concept, ConceptSource
from app.db.models.content_chunk import ContentChunk
from app.db.models.lab import Lab
from app.db.models.exercise import Exercise
from app.db.models.learning_record import LearningRecord
from app.db.models.conversation import Conversation
from app.db.models.message import Message
from app.db.models.model_config import ModelConfig, ModelRouteConfig
from app.db.models.llm_usage_log import LlmUsageLog
from app.db.models.exercise_submission import ExerciseSubmission
from app.db.models.review_item import ReviewItem
from app.db.models.episodic_memory import EpisodicMemory
from app.db.models.metacognitive_record import MetacognitiveRecord
from app.db.models.translation import Translation
from app.db.models.section_progress import SectionProgress
from app.db.models.bilibili_credential import BilibiliCredential
from app.db.models.whisper_config import WhisperConfig

__all__ = [
    "Base",
    "BaseMixin",
    "User",
    "Source",
    "SourceTask",
    "Course",
    "CourseSource",
    "Section",
    "Concept",
    "ConceptSource",
    "ContentChunk",
    "Lab",
    "Exercise",
    "LearningRecord",
    "Conversation",
    "Message",
    "ModelConfig",
    "ModelRouteConfig",
    "LlmUsageLog",
    "ExerciseSubmission",
    "ReviewItem",
    "EpisodicMemory",
    "MetacognitiveRecord",
    "Translation",
    "SectionProgress",
    "BilibiliCredential",
    "WhisperConfig",
]
