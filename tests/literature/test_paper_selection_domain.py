from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from module_agent.literature.domain.selection import PaperSelection


def test_paper_selection_accepts_valid_data() -> None:
    selected_at = datetime.now(timezone.utc)

    selection = PaperSelection(
        run_id=7,
        selected_paper_ids=[51, 42],
        code_requirements="Use PyTorch",
        selected_at=selected_at,
    )

    assert selection.run_id == 7
    assert selection.selected_paper_ids == [51, 42]
    assert selection.code_requirements == "Use PyTorch"
    assert selection.selected_at == selected_at


@pytest.mark.parametrize("run_id", [0, -1])
def test_paper_selection_rejects_non_positive_run_id(run_id: int) -> None:
    with pytest.raises(ValidationError):
        PaperSelection(run_id=run_id, selected_paper_ids=[42])


@pytest.mark.parametrize(
    "paper_ids",
    [[], [0], [-1], [42, 42]],
)
def test_paper_selection_rejects_invalid_paper_ids(
    paper_ids: list[int],
) -> None:
    with pytest.raises(ValidationError):
        PaperSelection(run_id=7, selected_paper_ids=paper_ids)
