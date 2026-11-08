import pytest

from module_agent.code.application.scoring import RepositoryScoringService
from module_agent.code.domain.repository import (
    RepositoryCandidate,
    RepositoryEvidence,
    RepositoryEvidenceType,
    RepositoryOrigin,
)
from module_agent.code.domain.request import CodePaperInput


def make_paper(**updates: object) -> CodePaperInput:
    values = {
        "paper_id": 1,
        "source": "openalex",
        "source_id": "W1",
        "title": "Reliable Rank Metrics for Graph Oversmoothing",
        "authors": ["Alice Zhang", "Bob Smith"],
        "doi": "https://doi.org/10.1000/graph.1",
    }
    values.update(updates)
    return CodePaperInput.model_validate(values)


def make_candidate(**updates: object) -> RepositoryCandidate:
    values = {
        "full_name": "alicezhang/graph-rank",
        "repository_url": "https://github.com/alicezhang/graph-rank",
        "owner_login": "alicezhang",
        "description": "Implementation for graph representation learning",
        "readme_text": "Reliable Rank Metrics for Graph Oversmoothing. DOI: 10.1000/graph.1",
    }
    values.update(updates)
    return RepositoryCandidate.model_validate(values)


def test_scorer_marks_title_doi_and_author_match_as_author_repository() -> None:
    scored = RepositoryScoringService().score(make_paper(), make_candidate())

    assert scored.origin is RepositoryOrigin.AUTHOR
    assert scored.confidence == 1.0
    assert {item.evidence_type for item in scored.evidence} == {
        RepositoryEvidenceType.DOI,
        RepositoryEvidenceType.TITLE,
        RepositoryEvidenceType.AUTHOR,
    }


def test_scorer_only_marks_direct_paper_link_as_official() -> None:
    candidate = make_candidate(readme_text=None, description=None)
    paper = make_paper(landing_page_url=str(candidate.repository_url))

    scored = RepositoryScoringService().score(paper, candidate)

    assert scored.origin is RepositoryOrigin.OFFICIAL
    assert scored.confidence == pytest.approx(1.0)
    assert scored.evidence[0].evidence_type is RepositoryEvidenceType.IMPLEMENTATION_URL


def test_scorer_does_not_call_title_only_match_official() -> None:
    candidate = make_candidate(
        owner_login="unrelated-user",
        readme_text="Reliable Rank Metrics for Graph Oversmoothing",
    )

    scored = RepositoryScoringService().score(make_paper(), candidate)

    assert scored.origin is RepositoryOrigin.UNKNOWN
    assert scored.confidence == pytest.approx(0.35)


def test_scorer_uses_keyword_evidence_for_partial_match() -> None:
    candidate = make_candidate(
        owner_login="unrelated-user",
        readme_text=None,
        description="rank metrics for graph models",
    )

    scored = RepositoryScoringService().score(make_paper(), candidate)

    assert scored.origin is RepositoryOrigin.UNKNOWN
    assert scored.evidence[0].evidence_type is RepositoryEvidenceType.KEYWORD
    assert 0 < scored.confidence < 0.2


def test_scorer_penalizes_archived_repository() -> None:
    service = RepositoryScoringService()
    active = service.score(make_paper(), make_candidate())
    archived = service.score(
        make_paper(),
        make_candidate(archived=True),
    )

    assert active.confidence == 1.0
    assert archived.confidence == 0.8


def test_score_many_orders_candidates_by_confidence() -> None:
    candidates = [
        make_candidate(
            full_name="other/partial",
            owner_login="other",
            readme_text=None,
            description="rank metrics for graph models",
        ),
        make_candidate(),
    ]

    scored = RepositoryScoringService().score_many(make_paper(), candidates)

    assert [candidate.full_name for candidate in scored] == [
        "alicezhang/graph-rank",
        "other/partial",
    ]


def test_rescoring_does_not_duplicate_evidence() -> None:
    service = RepositoryScoringService()
    first = service.score(make_paper(), make_candidate())
    second = service.score(make_paper(), first)

    assert second.evidence == first.evidence


def mentioned_link(source_url: str) -> RepositoryEvidence:
    return RepositoryEvidence(
        evidence_type=RepositoryEvidenceType.PAPER_URL,
        description="Repository URL found on a paper page or PDF",
        weight=0.95,  # Also exercise candidates produced by the old adapter.
        source_url=source_url,
    )


def test_publisher_thesaurus_is_not_official_elm_implementation() -> None:
    paper = make_paper(
        title="Fast, Simple and Accurate Handwritten Digit Classification",
        landing_page_url="https://doi.org/10.1371/journal.pone.0134254",
    )
    candidate = make_candidate(
        full_name="PLOS/plos-thesaurus",
        repository_url="https://github.com/PLOS/plos-thesaurus",
        owner_login="PLOS",
        description="The PLOS Thesaurus",
        readme_text="Welcome to the repository for the PLOS Thesaurus.",
        evidence=[mentioned_link(paper.landing_page_url)],
    )

    scored = RepositoryScoringService().score(paper, candidate)

    assert scored.origin is RepositoryOrigin.UNKNOWN
    assert scored.confidence < 0.7


def test_spiral_implementation_ranks_above_referenced_benchmark() -> None:
    title = "SPIRAL: A Novel Time Series to Image Transformation Method for Vision-Based Anomaly Detection"
    paper = make_paper(
        title=title,
        abstract=(
            "We evaluate on the TSB-AD benchmark. Our code is publicly available "
            "at: https://github.com/Smendowski/SPIRAL."
        ),
    )
    benchmark = make_candidate(
        full_name="TheDatumOrg/TSB-AD",
        repository_url="https://github.com/TheDatumOrg/TSB-AD",
        owner_login="TheDatumOrg",
        description="Time-Series Anomaly Detection Benchmark",
        readme_text="The Elephant in the Room: Towards A Reliable Time-Series Anomaly Detection Benchmark",
        evidence=[mentioned_link("https://papers.test/spiral.pdf")],
    )
    implementation = make_candidate(
        full_name="Smendowski/SPIRAL",
        repository_url="https://github.com/Smendowski/SPIRAL",
        owner_login="Smendowski",
        description=None,
        readme_text=f"Implementation of {title}",
    )

    best, other = RepositoryScoringService().score_many(
        paper, [benchmark, implementation]
    )

    assert best.full_name == "Smendowski/SPIRAL"
    assert best.origin is RepositoryOrigin.OFFICIAL
    assert best.confidence >= 0.7
    assert other.origin is RepositoryOrigin.UNKNOWN
    assert other.confidence < 0.7


def test_repeated_page_mentions_do_not_accumulate_into_authority() -> None:
    candidate = make_candidate(
        owner_login="unrelated",
        description=None,
        readme_text=None,
        evidence=[
            mentioned_link("https://papers.test/page"),
            mentioned_link("https://papers.test/paper.pdf"),
        ],
    )

    scored = RepositoryScoringService().score(make_paper(), candidate)

    assert scored.origin is RepositoryOrigin.UNKNOWN
    assert scored.confidence < 0.7


def test_unrelated_url_in_landing_page_query_is_not_direct_code_link() -> None:
    paper = make_paper(
        landing_page_url="https://publisher.test/?redirect=https://github.com/alicezhang/graph-rank"
    )
    candidate = make_candidate(owner_login="unrelated", readme_text=None)

    scored = RepositoryScoringService().score(paper, candidate)

    assert scored.origin is RepositoryOrigin.UNKNOWN
    assert scored.confidence < 0.7


def test_declared_link_without_independent_identity_is_not_official() -> None:
    paper = make_paper(
        abstract="Our code is available at https://github.com/unknown/repo."
    )
    candidate = make_candidate(
        full_name="unknown/repo",
        repository_url="https://github.com/unknown/repo",
        owner_login="unknown",
        description=None,
        readme_text=None,
    )

    scored = RepositoryScoringService().score(paper, candidate)

    assert scored.origin is RepositoryOrigin.UNKNOWN
    assert scored.confidence < 0.7


def test_readme_self_implementation_claim_is_usable_but_not_called_official() -> None:
    title="DropEdge: Towards Deep Graph Convolutional Networks on Node Classification"
    paper=make_paper(title=title,authors=["Yu Rong"],abstract="Codes will be made public upon publication.")
    candidate=make_candidate(full_name="DropEdge/DropEdge",repository_url="https://github.com/DropEdge/DropEdge",owner_login="DropEdge",readme_text=f"This is a Pytorch implementation of paper: {title}")
    result=RepositoryScoringService().score(paper,candidate)
    assert result.confidence>=.7
    assert result.origin is RepositoryOrigin.UNKNOWN


def test_related_paper_list_is_not_a_self_implementation_declaration() -> None:
    paper=make_paper()
    candidate=make_candidate(owner_login="other",readme_text="This repository implements a benchmark. Related papers: "+paper.title)
    result=RepositoryScoringService().score(paper,candidate)
    assert result.origin is RepositoryOrigin.UNKNOWN and result.confidence<.7
