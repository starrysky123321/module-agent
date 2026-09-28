import pytest

from module_agent.supervision.domain import (
    LEGAL_STATUS_TRANSITIONS,
    REQUIRED_STATE_FIELDS,
)
from module_agent.workflow.domain import WorkflowStatus


def test_transition_tables_cover_every_workflow_status() -> None:
    expected_statuses = set(WorkflowStatus)

    assert set(LEGAL_STATUS_TRANSITIONS) == expected_statuses
    assert set(REQUIRED_STATE_FIELDS) == expected_statuses


def test_terminal_statuses_have_no_successors() -> None:
    assert not LEGAL_STATUS_TRANSITIONS[WorkflowStatus.COMPLETED]
    assert not LEGAL_STATUS_TRANSITIONS[WorkflowStatus.FAILED]
    assert not LEGAL_STATUS_TRANSITIONS[WorkflowStatus.CANCELLED]


@pytest.mark.parametrize(
    ("current", "expected_next"),
    [
        (
            WorkflowStatus.CREATED,
            {
                WorkflowStatus.SEARCHING_LITERATURE,
                WorkflowStatus.FAILED,
                WorkflowStatus.CANCELLED,
            },
        ),
        (
            WorkflowStatus.SEARCHING_LITERATURE,
            {
                WorkflowStatus.WAITING_FOR_PAPER_SELECTION,
                WorkflowStatus.FAILED,
                WorkflowStatus.CANCELLED,
            },
        ),
        (
            WorkflowStatus.WAITING_FOR_PAPER_SELECTION,
            {
                WorkflowStatus.PREPARING_CODE,
                WorkflowStatus.FAILED,
                WorkflowStatus.CANCELLED,
            },
        ),
        (
            WorkflowStatus.PREPARING_CODE,
            {
                WorkflowStatus.WAITING_FOR_CODE,
                WorkflowStatus.CODE_READY,
                WorkflowStatus.FAILED,
                WorkflowStatus.CANCELLED,
            },
        ),
        (
            WorkflowStatus.WAITING_FOR_CODE,
            {
                WorkflowStatus.CODE_READY,
                WorkflowStatus.FAILED,
                WorkflowStatus.CANCELLED,
            },
        ),
        (
            WorkflowStatus.CODE_READY,
            {
                WorkflowStatus.VALIDATING,
                WorkflowStatus.FAILED,
                WorkflowStatus.CANCELLED,
            },
        ),
        (
            WorkflowStatus.VALIDATING,
            {
                WorkflowStatus.COMPLETED,
                WorkflowStatus.FAILED,
                WorkflowStatus.CANCELLED,
            },
        ),
    ],
)
def test_nonterminal_statuses_have_expected_successors(
    current: WorkflowStatus,
    expected_next: set[WorkflowStatus],
) -> None:
    assert LEGAL_STATUS_TRANSITIONS[current] == expected_next


@pytest.mark.parametrize(
    ("status", "required"),
    [
        (WorkflowStatus.CREATED, {"literature_run_id"}),
        (WorkflowStatus.SEARCHING_LITERATURE, {"literature_run_id"}),
        (
            WorkflowStatus.WAITING_FOR_PAPER_SELECTION,
            {"literature_run_id"},
        ),
        (
            WorkflowStatus.PREPARING_CODE,
            {"literature_run_id", "selected_paper_ids"},
        ),
        (
            WorkflowStatus.WAITING_FOR_CODE,
            {"literature_run_id", "selected_paper_ids"},
        ),
        (
            WorkflowStatus.CODE_READY,
            {
                "literature_run_id",
                "selected_paper_ids",
                "code_artifacts",
            },
        ),
        (
            WorkflowStatus.VALIDATING,
            {
                "literature_run_id",
                "selected_paper_ids",
                "code_artifacts",
            },
        ),
        (
            WorkflowStatus.COMPLETED,
            {
                "literature_run_id",
                "selected_paper_ids",
                "code_artifacts",
                "validation_reports",
            },
        ),
        (
            WorkflowStatus.FAILED,
            {"literature_run_id", "failure"},
        ),
        (
            WorkflowStatus.CANCELLED,
            {"literature_run_id"},
        ),
    ],
)
def test_statuses_require_expected_state_fields(
    status: WorkflowStatus,
    required: set[str],
) -> None:
    assert REQUIRED_STATE_FIELDS[status] == required


def test_transition_mappings_cannot_be_modified() -> None:
    with pytest.raises(TypeError):
        LEGAL_STATUS_TRANSITIONS[WorkflowStatus.CREATED] = frozenset()  # type: ignore[index]

    with pytest.raises(TypeError):
        REQUIRED_STATE_FIELDS[WorkflowStatus.CREATED] = frozenset()  # type: ignore[index]
