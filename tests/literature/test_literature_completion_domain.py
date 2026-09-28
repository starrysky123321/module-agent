import pytest
from pydantic import ValidationError

from module_agent.literature.domain.events import (
    LiteratureCompletedEvent,
)


def test_literature_completed_event_serializes_run_id() -> None:
    event = LiteratureCompletedEvent(run_id=7)

    assert event.model_dump(mode="json") == {"run_id": 7}
    assert LiteratureCompletedEvent.model_validate_json(
        event.model_dump_json()
    ) == event


@pytest.mark.parametrize("run_id", [0, -1])
def test_literature_completed_event_rejects_non_positive_run_id(
    run_id: int,
) -> None:
    with pytest.raises(ValidationError):
        LiteratureCompletedEvent(run_id=run_id)
