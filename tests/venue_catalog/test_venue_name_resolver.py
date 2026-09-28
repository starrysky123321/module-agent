from module_agent.venue_catalog.application.name_resolver import (
    generate_venue_name_candidates,
)


def test_name_candidates_returns_empty_list_for_missing_name() -> None:
    assert generate_venue_name_candidates(None) == []
    assert generate_venue_name_candidates("   ") == []


def test_name_candidates_keeps_an_ordinary_name_once() -> None:
    assert generate_venue_name_candidates(" CVPR ") == ["CVPR"]


def test_name_candidates_removes_proceedings_prefix() -> None:
    name = "Proceedings of the AAAI Conference on Artificial Intelligence"

    assert generate_venue_name_candidates(name) == [
        name,
        "AAAI Conference on Artificial Intelligence",
    ]
