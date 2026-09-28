from uuid import uuid4

import pytest

from module_agent.code.domain.jobs import ComputeTarget
from module_agent.workflow.domain import SupervisorStep, WorkflowStatus
from module_agent.workflow.lifecycle import ModuleWorkflowRunStatus
from module_agent.workflow.state import (
    apply_timeout_failure,
    build_initial_state,
    failure_message,
    lifecycle_status_for_graph,
    resumable_wait_status,
    validate_run_id,
    workflow_config,
)


def test_workflow_identity_helpers_reject_bool_and_build_thread_id() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        validate_run_id(True)

    validate_run_id(7)
    assert workflow_config(7)["configurable"]["thread_id"] == (
        "literature-run:7"
    )


def test_build_initial_state_serializes_checkpoint_values() -> None:
    trace_id = uuid4()

    state = build_initial_state(
        run_id=7,
        trace_id=trace_id,
        code_requirements="Use PyTorch",
        validation_policy=None,
        sandbox_options=None,
        validation_requirements=None,
        compute_target=ComputeTarget.CPU,
        status=WorkflowStatus.SEARCHING_LITERATURE,
        next_step=SupervisorStep.LITERATURE,
    )

    assert state["trace_id"] == str(trace_id)
    assert state["validation_policy"]["mode"] == "static"
    assert state["compute_target"] == "cpu"
    assert state["status"] == "searching_literature"


def test_graph_status_mappings_only_accept_known_strings() -> None:
    assert lifecycle_status_for_graph("completed") is (
        ModuleWorkflowRunStatus.COMPLETED
    )
    assert lifecycle_status_for_graph(None) is None
    assert resumable_wait_status("waiting_for_code") is (
        ModuleWorkflowRunStatus.WAITING_FOR_CODE
    )
    assert resumable_wait_status("completed") is None


def test_timeout_failure_preserves_attempt_and_extracts_message() -> None:
    values: dict[str, object] = {
        "next_step": "validation",
        "attempts": {"validation": 3},
    }

    apply_timeout_failure(values)

    assert values["status"] == "failed"
    assert values["attempts"] == {"validation": 3}
    assert failure_message(values) == "Workflow deadline exceeded"
