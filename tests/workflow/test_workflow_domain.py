import pytest
from pydantic import ValidationError

from module_agent.workflow.domain import (
    LiteratureCompletionSignal,
    LiteratureWaitInterrupt,
    ModuleWorkflowStartRequest,
)
from module_agent.validation.domain import ValidationMode


def test_literature_wait_interrupt_contains_run_context() -> None:
    payload = LiteratureWaitInterrupt(literature_run_id=7)

    assert payload.literature_run_id == 7
    assert payload.message == "Waiting for literature search to complete"


def test_literature_completion_signal_contains_run_id() -> None:
    signal = LiteratureCompletionSignal(literature_run_id=7)

    assert signal.model_dump(mode="json") == {"literature_run_id": 7}


def test_workflow_start_defaults_to_static_validation() -> None:
    request = ModuleWorkflowStartRequest()

    assert request.validation_policy.mode is ValidationMode.STATIC
    assert request.sandbox_options is None


def test_workflow_start_accepts_explicit_sandbox_configuration() -> None:
    request = ModuleWorkflowStartRequest.model_validate(
        {
            "validation_policy": {"mode": "sandbox"},
            "sandbox_options": {
                "import_modules": ["package"],
            },
        }
    )

    assert request.validation_policy.mode is ValidationMode.SANDBOX
    assert request.sandbox_options is not None


def test_workflow_start_rejects_sandbox_options_in_static_mode() -> None:
    with pytest.raises(ValidationError, match="cannot include sandbox"):
        ModuleWorkflowStartRequest.model_validate(
            {"sandbox_options": {"import_modules": ["package"]}}
        )


@pytest.mark.parametrize("run_id", [0, -1])
def test_literature_workflow_contracts_reject_non_positive_run_id(
    run_id: int,
) -> None:
    with pytest.raises(ValidationError):
        LiteratureWaitInterrupt(literature_run_id=run_id)

    with pytest.raises(ValidationError):
        LiteratureCompletionSignal(literature_run_id=run_id)
