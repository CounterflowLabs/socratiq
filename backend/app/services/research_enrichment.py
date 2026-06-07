"""Curated research enrichment for generated lessons.

This first pass is intentionally deterministic. It gives the course writer a
small set of vetted frontier references without doing live web search during
Celery generation, so lesson output stays reproducible and cheap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from app.models.research import ResearchCard


class _ChunkLike(Protocol):
    text: str
    metadata_: dict


@dataclass(frozen=True)
class _CuratedReference:
    card: ResearchCard
    triggers: tuple[str, ...]


_CURATED_REFERENCES: tuple[_CuratedReference, ...] = (
    _CuratedReference(
        card=ResearchCard(
            type="misconception_boundary",
            title="Feature detectors are a useful intuition, not a one-neuron promise",
            source_title="Scaling Monosemanticity: Extracting Interpretable Features from Claude 3 Sonnet",
            url="https://transformer-circuits.pub/2024/scaling-monosemanticity/index.html",
            published_at="2024-05-21",
            source_type="research_blog",
            relevance=(
                "Modern interpretability work often studies features as sparse "
                "activation patterns, which complicates the simple story that a "
                "single neuron cleanly maps to one human-readable concept."
            ),
            use_as="boundary_or_extension",
            concepts=["feature_hierarchy", "hidden_layer", "interpretability"],
            risk_note=(
                "Use only as a boundary note; the original lesson may be about "
                "small vision networks, while this reference studies language models."
            ),
            confidence=0.88,
        ),
        triggers=(
            "hidden layer",
            "hidden_layer",
            "feature",
            "feature_hierarchy",
            "edge_detection",
            "neuron",
            "loop",
            "边缘",
            "特征",
            "隐藏层",
        ),
    ),
    _CuratedReference(
        card=ResearchCard(
            type="engineering_note",
            title="Open sparse autoencoders as model microscopes",
            source_title="Gemma Scope: Open Sparse Autoencoders Everywhere All At Once on Gemma 2",
            url="https://arxiv.org/abs/2408.05147",
            published_at="2024-08-09",
            source_type="paper",
            relevance=(
                "Gemma Scope released sparse autoencoders across Gemma 2 layers, "
                "showing how researchers operationalize the idea of inspecting "
                "internal representations in current open models."
            ),
            use_as="engineering_context",
            concepts=["sparse_autoencoder", "interpretability", "feature"],
            risk_note=(
                "This is an extension reference, not required background for "
                "understanding a first neural-network lesson."
            ),
            confidence=0.84,
        ),
        triggers=(
            "interpretability",
            "feature",
            "representation",
            "hidden layer",
            "activation",
            "表征",
            "可解释",
            "激活",
        ),
    ),
    _CuratedReference(
        card=ResearchCard(
            type="frontier_note",
            title="Learnable edge functions as an alternative to classic MLPs",
            source_title="KAN: Kolmogorov-Arnold Networks",
            url="https://arxiv.org/abs/2404.19756",
            published_at="2024-04-30",
            source_type="paper",
            relevance=(
                "KANs revisit the classic MLP building block by replacing fixed "
                "node activations and linear weights with learnable functions on "
                "edges, making them a useful frontier contrast after weight, bias, "
                "and activation are introduced."
            ),
            use_as="boundary_or_extension",
            concepts=["mlp", "activation_function", "weight", "kan"],
            risk_note=(
                "Mention as a research direction only; do not imply KANs replace "
                "standard MLPs in mainstream introductory practice."
            ),
            confidence=0.8,
        ),
        triggers=(
            "mlp",
            "weight",
            "weights",
            "bias",
            "activation",
            "sigmoid",
            "relu",
            "weighted_sum",
            "权重",
            "偏置",
            "激活",
        ),
    ),
    _CuratedReference(
        card=ResearchCard(
            type="engineering_note",
            title="Sparse circuits connect parameters to executable behavior",
            source_title="Understanding neural networks through sparse circuits",
            url="https://openai.com/fa-IR/index/understanding-neural-networks-through-sparse-circuits/",
            published_at=None,
            source_type="research_blog",
            relevance=(
                "Sparse-circuit work gives a concrete engineering lens for asking "
                "which small parts of a model are necessary and sufficient for a "
                "specific behavior."
            ),
            use_as="engineering_context",
            concepts=["circuit", "matrix_vector_multiplication", "parameter"],
            risk_note=(
                "Use for advanced extension; it assumes the learner already has "
                "the basic layer/function view."
            ),
            confidence=0.76,
        ),
        triggers=(
            "matrix",
            "vector",
            "function",
            "parameter",
            "circuit",
            "linear algebra",
            "矩阵",
            "向量",
            "函数",
            "参数",
        ),
    ),
)


class ResearchEnrichmentService:
    """Select relevant research cards for a lesson section.

    Two pools, matched to the section the same way (keyword/concept overlap):
      - the built-in curated set (``_CURATED_REFERENCES``), and
      - ``extra_cards``: live-fetched references (e.g. arXiv) cached at
        ingestion on the source and handed in here. Both carry real URLs, so a
        ``further_reading`` block can cite them with a verified ``url``.
    """

    def __init__(self, extra_cards: list[ResearchCard] | None = None) -> None:
        self._extra_cards = list(extra_cards or [])

    def enrich(
        self,
        *,
        section_title: str,
        chunks: Iterable[_ChunkLike],
        max_cards: int = 3,
    ) -> list[ResearchCard]:
        haystack_parts = [section_title]
        for chunk in chunks:
            metadata = chunk.metadata_ or {}
            haystack_parts.append(chunk.text)
            for key in ("topic", "summary"):
                value = metadata.get(key)
                if isinstance(value, str):
                    haystack_parts.append(value)
            for key in ("concepts", "key_terms"):
                values = metadata.get(key)
                if isinstance(values, list):
                    haystack_parts.extend(str(v) for v in values)

        haystack = " ".join(haystack_parts).lower()
        scored: list[tuple[int, float, ResearchCard]] = []
        for ref in _CURATED_REFERENCES:
            score = sum(1 for trigger in ref.triggers if trigger.lower() in haystack)
            if score:
                scored.append((score, ref.card.confidence, ref.card))
        # Fetched cards match on the concepts they were queried with.
        for card in self._extra_cards:
            score = sum(1 for c in card.concepts if c and c.lower() in haystack)
            if score:
                scored.append((score, card.confidence, card))

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        out: list[ResearchCard] = []
        seen: set[str] = set()
        for _, _, card in scored:
            key = (card.url or card.title).strip().lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(card)
            if len(out) >= max_cards:
                break
        return out


# Key under which ingestion caches live-fetched reference cards on the source.
FETCHED_REFERENCES_KEY = "fetched_research_cards"


def cards_from_metadata(raw: object) -> list[ResearchCard]:
    """Rebuild ``ResearchCard``s from cached metadata dicts (skip malformed)."""
    cards: list[ResearchCard] = []
    if not isinstance(raw, list):
        return cards
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            cards.append(ResearchCard(**item))
        except Exception:  # noqa: BLE001
            continue
    return cards
