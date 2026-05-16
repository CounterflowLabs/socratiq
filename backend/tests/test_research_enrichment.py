"""Tests for curated research enrichment."""

from types import SimpleNamespace

from app.services.research_enrichment import ResearchEnrichmentService


def _chunk(text: str, metadata: dict) -> SimpleNamespace:
    return SimpleNamespace(text=text, metadata_=metadata)


def test_enrich_selects_interpretability_cards_for_feature_sections():
    service = ResearchEnrichmentService()
    cards = service.enrich(
        section_title="Hidden layers as feature detectors",
        chunks=[
            _chunk(
                "A hidden layer may detect edges and loops before digits.",
                {
                    "concepts": ["feature_hierarchy", "edge_detection"],
                    "key_terms": ["hidden layer"],
                },
            )
        ],
    )

    assert cards
    assert cards[0].source_title.startswith("Scaling Monosemanticity")
    assert cards[0].use_as == "boundary_or_extension"


def test_enrich_selects_kan_for_weight_activation_sections():
    service = ResearchEnrichmentService()
    cards = service.enrich(
        section_title="Weights, bias, and sigmoid activation",
        chunks=[
            _chunk(
                "Weights and bias feed a sigmoid activation function.",
                {"concepts": ["weighted_sum", "activation_function"]},
            )
        ],
    )

    assert any(card.source_title == "KAN: Kolmogorov-Arnold Networks" for card in cards)


def test_enrich_returns_empty_when_no_trigger_matches():
    service = ResearchEnrichmentService()
    cards = service.enrich(
        section_title="Sponsor outro",
        chunks=[_chunk("Thanks to the sponsor.", {"concepts": []})],
    )

    assert cards == []

