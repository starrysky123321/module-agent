import pytest
from pydantic import ValidationError

from module_agent.literature.domain.recommendation import LiteratureRunPaper


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("paper_id", 0),
        ("position", -1),
        ("relevance_score", -0.01),
        ("relevance_score", 1.01),
    ],
)
def test_literature_run_paper_rejects_invalid_values(
    field: str,
    value: object,
) -> None:
    values: dict[str, object] = {
        "paper_id": 1,
        "position": 0,
        "relevance_score": 0.8,
    }
    values[field] = value

    with pytest.raises(ValidationError):
        LiteratureRunPaper.model_validate(values)


def test_literature_run_paper_has_safe_explanation_defaults() -> None:
    run_paper = LiteratureRunPaper(paper_id=1, position=0)

    assert run_paper.relevance_score == 0.0
    assert run_paper.relevance_reason == ""
    assert run_paper.matched_terms == []
