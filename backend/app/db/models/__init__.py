"""Database models package. Import all models here for Alembic metadata discovery."""

from app.db.models.base import Base, BaseMixin
from app.db.models.user import User
from app.db.models.source import Source
from app.db.models.course import Course, CourseSource, Section
from app.db.models.concept import Concept, ConceptSource
from app.db.models.content_chunk import ContentChunk
from app.db.models.lab import Lab
from app.db.models.exercise import Exercise
from app.db.models.learning_record import LearningRecord
from app.db.models.conversation import Conversation
from app.db.models.message import Message
from app.db.models.model_config import ModelConfig, ModelRouteConfig

__all__ = [
    "Base",
    "BaseMixin",
    "User",
    "Source",
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
]
