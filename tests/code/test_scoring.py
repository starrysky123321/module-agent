import pytest

from module_agent.code.application.scoring import RepositoryScoringService
from module_agent.code.domain.repository import (
    RepositoryCandidate,
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
    assert scored.evidence[0].evidence_type is RepositoryEvidenceType.PAPER_URL


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
