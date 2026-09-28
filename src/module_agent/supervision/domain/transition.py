from collections.abc import Mapping
from types import MappingProxyType

from module_agent.workflow.domain import WorkflowStatus


LEGAL_STATUS_TRANSITIONS: Mapping[
    WorkflowStatus,
    frozenset[WorkflowStatus],
] = MappingProxyType({
    WorkflowStatus.CREATED: frozenset(
        {
            WorkflowStatus.SEARCHING_LITERATURE,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }
    ),
    
    WorkflowStatus.SEARCHING_LITERATURE: frozenset(
        {
            WorkflowStatus.WAITING_FOR_PAPER_SELECTION,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }
    ),
    
    WorkflowStatus.WAITING_FOR_PAPER_SELECTION: frozenset(
        {
            WorkflowStatus.PREPARING_CODE,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }
    ),
    
    WorkflowStatus.PREPARING_CODE: frozenset(
        {
            WorkflowStatus.WAITING_FOR_CODE,
            WorkflowStatus.CODE_READY,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }
    ),

    WorkflowStatus.WAITING_FOR_CODE: frozenset(
        {
            WorkflowStatus.CODE_READY,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }
    ),
    
    WorkflowStatus.CODE_READY: frozenset(
        {
            WorkflowStatus.VALIDATING,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }
    ),
    
    WorkflowStatus.VALIDATING: frozenset(
        {
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }
    ),
    WorkflowStatus.COMPLETED: frozenset(),
    WorkflowStatus.FAILED: frozenset(),
    WorkflowStatus.CANCELLED: frozenset(),
})



REQUIRED_STATE_FIELDS: Mapping[
    WorkflowStatus,
    frozenset[str],
] = MappingProxyType({
    WorkflowStatus.CREATED: frozenset(
        {
            "literature_run_id",
        }
    ),
    
    WorkflowStatus.SEARCHING_LITERATURE: frozenset(
        {
            "literature_run_id",
        }
    ),
    
    WorkflowStatus.WAITING_FOR_PAPER_SELECTION: frozenset(
        {
            "literature_run_id",
        }
    ),
    
    WorkflowStatus.PREPARING_CODE: frozenset(
        {
            "literature_run_id",
            "selected_paper_ids",
        }
    ),

    WorkflowStatus.WAITING_FOR_CODE: frozenset(
        {
            "literature_run_id",
            "selected_paper_ids",
        }
    ),
    
    WorkflowStatus.CODE_READY: frozenset(
        {
            "literature_run_id",
            "selected_paper_ids",
            "code_artifacts",
        }
    ),
    
    WorkflowStatus.VALIDATING: frozenset(
        {
            "literature_run_id",
            "selected_paper_ids",
            "code_artifacts",
        }
    ),
    
    WorkflowStatus.COMPLETED: frozenset(
        {
            "literature_run_id",
            "selected_paper_ids",
            "code_artifacts",
            "validation_reports",
        }
    ),
    
    WorkflowStatus.FAILED: frozenset(
        {
            "literature_run_id",
            "failure",
        }
    ),
    WorkflowStatus.CANCELLED: frozenset(
        {
            "literature_run_id",
        }
    ),
})
