import pytest

from module_agent.literature.domain.search import PaperSearchResult
from module_agent.literature.application.deduplication import (
    deduplicate_papers,
    paper_preference_key,
)


def _paper(**updates: object) -> PaperSearchResult:
    values: dict[str, object] = {
        "source": "openalex",
        "source_id": "W123",
        "title": "Example paper",
    }
    values.update(updates)
    return PaperSearchResult.model_validate(values)


@pytest.mark.parametrize(
    ("publication_type", "expected_rank"),
    [
        ("preprint", 0),
        ("POSTED-CONTENT", 0),
        (" posted content ", 0),
        (None, 1),
        ("", 1),
        ("JournalArticle", 2),
        ("Conference", 2),
    ],
)
def test_preference_key_ranks_publication_type(
    publication_type: str | None,
    expected_rank: int,
) -> None:
    key = paper_preference_key(
        _paper(publication_type=publication_type)
    )

    assert key[0] == expected_rank


def test_preference_key_prioritizes_published_version_over_preprint() -> None:
    published = _paper(
        publication_type="JournalArticle",
        cited_by_count=1,
    )
    preprint = _paper(
        publication_type="preprint",
        venue="arXiv",
        doi="10.1000/preprint",
        abstract="Complete abstract",
        cited_by_count=100,
    )

    assert paper_preference_key(published) > paper_preference_key(preprint)


def test_preference_key_uses_metadata_then_citations_as_tiebreakers() -> None:
    sparse = _paper(
        publication_type="JournalArticle",
        cited_by_count=100,
    )
    richer = _paper(
        publication_type="JournalArticle",
        venue="TGRS",
        doi="10.1000/published",
        abstract="Complete abstract",
        cited_by_count=1,
    )

    assert paper_preference_key(richer) > paper_preference_key(sparse)

    less_cited = _paper(
        publication_type="JournalArticle",
        venue="TGRS",
        doi="10.1000/published",
        abstract="Complete abstract",
        cited_by_count=1,
    )
    more_cited = less_cited.model_copy(update={"cited_by_count": 2})

    assert paper_preference_key(more_cited) > paper_preference_key(less_cited)


def test_deduplicate_papers_prefers_published_version_of_same_title() -> None:
    preprint = _paper(
        source_id="preprint",
        title="SEMA-YOLO: Lightweight Small-Object Detection",
        doi="10.1000/preprint",
        publication_type="preprint",
        cited_by_count=100,
    )
    published = _paper(
        source_id="published",
        title="sema yolo lightweight small object detection",
        doi="10.1000/published",
        publication_type="JournalArticle",
        cited_by_count=1,
    )

    assert deduplicate_papers([preprint, published]) == [published]


def test_deduplicate_papers_matches_same_doi_with_different_titles() -> None:
    sparse = _paper(
        source_id="sparse",
        title="Early title",
        doi="https://doi.org/10.1000/EXAMPLE",
        cited_by_count=1,
    )
    richer = _paper(
        source_id="richer",
        title="Final published title",
        doi="10.1000/example",
        venue="CVPR",
        cited_by_count=2,
    )

    assert deduplicate_papers((sparse, richer)) == [richer]


def test_deduplicate_papers_merges_transitively_and_preserves_group_order() -> None:
    first = _paper(
        source_id="first",
        title="Original title",
        doi="10.1000/shared",
    )
    independent = _paper(
        source_id="independent",
        title="Independent paper",
        doi="10.1000/independent",
    )
    bridge = _paper(
        source_id="bridge",
        title="Final title",
        doi="10.1000/shared",
    )
    preferred = _paper(
        source_id="preferred",
        title="Final title",
        doi="10.1000/final",
        publication_type="JournalArticle",
    )

    result = deduplicate_papers([first, independent, bridge, preferred])

    assert [paper.source_id for paper in result] == [
        "preferred",
        "independent",
    ]


def test_deduplicate_papers_returns_empty_list_for_empty_input() -> None:
    assert deduplicate_papers(()) == []


def test_dropedge_title_variants_and_version_urls_are_one_paper() -> None:
    original = _paper(
        source_id="W2996268457",
        title="DropEdge: Towards Deep Graph Convolutional Networks on Node Classification",
        doi="10.48550/arxiv.1907.10903",
        abstract="Complete abstract",
    )
    revised = _paper(
        source_id="W3180180626",
        title="DropEdge: Towards the Very Deep Graph Convolutional Networks for Node Classification",
        landing_page_url="https://arxiv.org/abs/1907.10903v2",
    )
    assert deduplicate_papers([original, revised]) == [original]


@pytest.mark.parametrize("value", [
    "https://arxiv.org/pdf/1907.10903v3.pdf",
    "https://arxiv.org/html/1907.10903v2",
    "https://doi.org/10.48550/arXiv.1907.10903",
    "arXiv:1907.10903v2",
])
def test_arxiv_aliases_are_normalized(value: str) -> None:
    from module_agent.literature.domain.normalization import normalize_arxiv_id
    assert normalize_arxiv_id(value) == "1907.10903"


def test_arxiv_legacy_id_is_normalized() -> None:
    from module_agent.literature.domain.normalization import normalize_arxiv_id
    assert normalize_arxiv_id("https://arxiv.org/abs/math.GT/0309136v2") == "math.gt/0309136"


@pytest.mark.parametrize("value", [
    "https://unrelated.test/abs/1907.10903",
    "https://arxiv.org.evil.test/abs/1907.10903",
    "https://publisher.test/?url=https://arxiv.org/abs/1907.10903",
    "10.1109/1907.10903",
])
def test_unrelated_urls_do_not_supply_arxiv_identity(value: str) -> None:
    from module_agent.literature.domain.normalization import normalize_arxiv_id
    assert normalize_arxiv_id(value) is None
