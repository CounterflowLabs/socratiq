"""Knowledge graph service — concept visualization with mastery tracking."""

import logging
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.concept import Concept, ConceptSource
from app.db.models.course import CourseSource
from app.db.models.review_item import ReviewItem
from app.db.models.exercise import Exercise
from app.db.models.exercise_submission import ExerciseSubmission

logger = logging.getLogger(__name__)


class KnowledgeGraphNode(BaseModel):
    id: str
    label: str
    category: str | None = None
    description: str | None = None
    kind: str = "related"
    mastery: float = 0.0
    section_id: str | None = None


class KnowledgeGraphEdge(BaseModel):
    source: str
    target: str
    relationship: str = "prerequisite"


class KnowledgeGraphService:
    def __init__(self, db: AsyncSession):
        self._db = db

    @staticmethod
    def calculate_mastery_score(
        review_easiness: float | None,
        exercise_scores: list[float],
    ) -> float:
        """Calculate concept mastery: 0.4 * review + 0.6 * exercise.

        Args:
            review_easiness: SM-2 easiness factor (0–5 scale) from ReviewItem,
                or None if the user has no review history for this concept.
            exercise_scores: List of exercise submission scores (0–100 scale).

        Returns:
            Mastery score in [0, 1].
        """
        review_score = (review_easiness / 5.0) if review_easiness is not None else 0.0
        exercise_score = (
            sum(exercise_scores) / len(exercise_scores) / 100.0
            if exercise_scores
            else 0.0
        )

        has_review = review_easiness is not None
        has_exercise = len(exercise_scores) > 0

        if has_review and has_exercise:
            return review_score * 0.4 + exercise_score * 0.6
        elif has_review:
            return review_score * 0.4
        elif has_exercise:
            return exercise_score * 0.6
        return 0.0

    async def get_graph(
        self,
        course_id: UUID,
        user_id: UUID,
        max_depth: int = 2,
    ) -> dict:
        """Build knowledge graph for a course.

        Args:
            course_id: UUID of the course.
            user_id: UUID of the current user (for mastery calculation).
            max_depth: Unused depth limit (reserved for future traversal logic).

        Returns:
            Dict with ``nodes`` and ``edges`` lists.
        """
        # Resolve source_ids for this course, then concept_ids linked to those sources
        source_ids_subq = select(CourseSource.source_id).where(
            CourseSource.course_id == course_id
        )
        concept_ids_subq = select(ConceptSource.concept_id).where(
            ConceptSource.source_id.in_(source_ids_subq)
        )

        result = await self._db.execute(
            select(Concept).where(Concept.id.in_(concept_ids_subq)).limit(200)
        )
        concepts = result.scalars().all()

        if not concepts:
            return {"nodes": [], "edges": []}

        concept_ids_set = {c.id for c in concepts}
        prerequisite_ids = {
            prereq_id
            for concept in concepts
            for prereq_id in (concept.prerequisites or [])
            if prereq_id in concept_ids_set
        }
        nodes: list[KnowledgeGraphNode] = []
        edges: list[KnowledgeGraphEdge] = []

        for concept in concepts:
            # Review easiness for this user + concept
            review_result = await self._db.execute(
                select(ReviewItem.easiness).where(
                    ReviewItem.user_id == user_id,
                    ReviewItem.concept_id == concept.id,
                )
            )
            review_easiness = review_result.scalar_one_or_none()

            # Exercise IDs that cover this concept
            # Use raw ANY() because SQLAlchemy ARRAY .any() is not supported here
            ex_result = await self._db.execute(
                select(Exercise.id).where(
                    text("cast(:cid as uuid) = ANY(concepts)").bindparams(
                        cid=str(concept.id)
                    )
                )
            )
            exercise_ids = [row[0] for row in ex_result.all()]

            exercise_scores: list[float] = []
            if exercise_ids:
                sub_result = await self._db.execute(
                    select(ExerciseSubmission.score).where(
                        ExerciseSubmission.user_id == user_id,
                        ExerciseSubmission.exercise_id.in_(exercise_ids),
                        ExerciseSubmission.score.isnot(None),
                    )
                )
                exercise_scores = [float(row[0]) for row in sub_result.all()]

            mastery = self.calculate_mastery_score(
                review_easiness=float(review_easiness) if review_easiness is not None else None,
                exercise_scores=exercise_scores,
            )

            nodes.append(
                KnowledgeGraphNode(
                    id=str(concept.id),
                    label=concept.name,
                    category=concept.category,
                    description=concept.description,
                    kind="current" if concept.id not in prerequisite_ids else "related",
                    mastery=round(mastery, 2),
                )
            )

            # Build edges from prerequisites that are also in this graph
            if concept.prerequisites:
                for prereq_id in concept.prerequisites:
                    if prereq_id in concept_ids_set:
                        edges.append(
                            KnowledgeGraphEdge(
                                source=str(prereq_id),
                                target=str(concept.id),
                            )
                        )

        return {
            "nodes": [n.model_dump() for n in nodes],
            "edges": [e.model_dump() for e in edges],
        }
