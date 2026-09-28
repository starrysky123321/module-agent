from module_agent.literature.domain.paper import Paper


def test_paper_has_safe_persistence_defaults() -> None:
    paper = Paper(
        source="openalex",
        source_id="W123",
        title="Example Paper",
        authors=[],
    )

    assert paper.id is None
    assert paper.venue_id is None
    assert paper.venue_name is None
    assert paper.is_open_access is False
    assert paper.cited_by_count == 0


def test_paper_keeps_raw_venue_name_and_resolved_venue_id() -> None:
    paper = Paper(
        id=10,
        source="openalex",
        source_id="W456",
        title="AAAI Paper",
        authors=["Example Author"],
        venue_id=42,
        venue_name="Proceedings of the AAAI Conference on Artificial Intelligence",
    )

    assert paper.venue_id == 42
    assert paper.venue_name.startswith("Proceedings of the AAAI")
