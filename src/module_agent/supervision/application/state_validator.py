from collections.abc import Mapping
from typing import cast

from pydantic import ValidationError

from module_agent.code.domain.artifact import CodeArtifact
from module_agent.supervision.domain import (
    REQUIRED_STATE_FIELDS,
    WorkflowFailure,
    WorkflowStateValidationError,
)
from module_agent.validation.domain.report import ValidationReport
from module_agent.workflow.domain import (
    ModuleGraphState,
    SupervisorStep,
    WorkflowStatus,
)


class WorkflowStateValidator:
    """校验输入或运行状态。"""
    def validate(
        self,
        state: ModuleGraphState,
    ) -> WorkflowStatus:
        """校验输入和业务约束。"""
        status = self._read_status(state)
        values = cast(Mapping[str, object], state)

        missing_fields = sorted(
            field
            for field in REQUIRED_STATE_FIELDS[status]
            if self._is_missing(values.get(field))
        )

        if missing_fields:
            raise WorkflowStateValidationError(
                f"Workflow state {status.value!r} is missing required "
                f"fields: {', '.join(missing_fields)}"
            )

        self._validate_dependencies(status, values)

        literature_run_id, selected_paper_ids = (
            self._validate_identifiers(values)
        )

        artifacts = self._validate_artifacts(
            values,
            selected_paper_ids,
        )
        
        self._validate_reports(
            values,
            literature_run_id,
            artifacts,
        )
        self._validate_attempts(values)
        self._validate_failure(values)


        return status

    
    @staticmethod
    def _read_status(state: ModuleGraphState) -> WorkflowStatus:
        raw_status = state.get("status")

        if raw_status is None:
            raise WorkflowStateValidationError("Workflow state has no status")

        try:
            return WorkflowStatus(raw_status)
        except (TypeError, ValueError) as exc:
            raise WorkflowStateValidationError(
                f"Unknown workflow status: {raw_status!r}"
            ) from exc
            
    @staticmethod
    def _is_missing(value: object) -> bool:
        if value is None:
            return True
        
        if isinstance(value, str):
            return not value.strip()
        
        if isinstance(value, (list, tuple, set, dict)):
            return not value
        
        return False
    
    
    @classmethod
    def _validate_dependencies(
        cls,
        status: WorkflowStatus,
        values: Mapping[str, object],
    ) -> None:
        has_selection = not cls._is_missing(
            values.get("selected_paper_ids")
        )
        has_artifacts = not cls._is_missing(
            values.get("code_artifacts")
        )
        has_reports = not cls._is_missing(
            values.get("validation_reports")
        )
        has_failure = not cls._is_missing(
            values.get("failure")
        )

        if has_artifacts and not has_selection:
            raise WorkflowStateValidationError(
                "Code artifacts require selected paper ids"
            )

        if has_reports and not has_artifacts:
            raise WorkflowStateValidationError(
                "Validation reports require code artifacts"
            )

        if (
            has_selection
            and status
            in {
                WorkflowStatus.CREATED,
                WorkflowStatus.SEARCHING_LITERATURE,
                WorkflowStatus.WAITING_FOR_PAPER_SELECTION,
            }
        ):
            raise WorkflowStateValidationError(
                "Selected paper ids appeared before the code stage"
            )

        if (
            has_artifacts
            and status
            in {
                WorkflowStatus.CREATED,
                WorkflowStatus.SEARCHING_LITERATURE,
                WorkflowStatus.WAITING_FOR_PAPER_SELECTION,
                WorkflowStatus.PREPARING_CODE,
            }
        ):
            raise WorkflowStateValidationError(
                "Code artifacts appeared before code completion"
            )

        if (
            has_reports
            and status
            not in {
                WorkflowStatus.COMPLETED,
                WorkflowStatus.FAILED,
            }
        ):
            raise WorkflowStateValidationError(
                "Validation reports appeared before workflow completion"
            )

        if has_failure and status is not WorkflowStatus.FAILED:
            raise WorkflowStateValidationError(
                "A workflow failure requires failed status"
            )
            
            
    @classmethod
    def _validate_identifiers(
        cls,
        values: Mapping[str, object],
    ) -> tuple[int, list[int]]:
        literature_run_id = values.get("literature_run_id")

        if (
            type(literature_run_id) is not int
            or literature_run_id <= 0
        ):
            raise WorkflowStateValidationError(
                "literature_run_id must be a positive integer"
            )

        raw_paper_ids = values.get("selected_paper_ids")

        if cls._is_missing(raw_paper_ids):
            return literature_run_id, []

        if not isinstance(raw_paper_ids, list):
            raise WorkflowStateValidationError(
                "selected_paper_ids must be a list"
            )

        if any(
            type(paper_id) is not int or paper_id <= 0
            for paper_id in raw_paper_ids
        ):
            raise WorkflowStateValidationError(
                "Selected paper ids must be positive integers"
            )

        if len(raw_paper_ids) != len(set(raw_paper_ids)):
            raise WorkflowStateValidationError(
                "Selected paper ids must be unique"
            )

        return literature_run_id, raw_paper_ids

    @classmethod
    def _validate_attempts(
        cls,
        values: Mapping[str, object],
    ) -> dict[SupervisorStep, int]:
        raw_attempts = values.get("attempts")

        if raw_attempts is None:
            return {}

        if not isinstance(raw_attempts, dict):
            raise WorkflowStateValidationError(
                "attempts must be a dictionary"
            )

        attempts: dict[SupervisorStep, int] = {}
        for raw_step, attempt in raw_attempts.items():
            try:
                step = SupervisorStep(raw_step)
            except (TypeError, ValueError) as exc:
                raise WorkflowStateValidationError(
                    f"Unknown attempt step: {raw_step!r}"
                ) from exc

            if step is SupervisorStep.FINISH:
                raise WorkflowStateValidationError(
                    "The finish step cannot have execution attempts"
                )

            if type(attempt) is not int or attempt < 1:
                raise WorkflowStateValidationError(
                    f"Attempt count for {step.value!r} must be a "
                    "positive integer"
                )

            attempts[step] = attempt

        return attempts
    
    
    
    @classmethod
    def _validate_artifacts(
        cls,
        values: Mapping[str, object],
        selected_paper_ids: list[int],
    ) -> list[CodeArtifact]:
        raw_artifacts = values.get("code_artifacts")

        if cls._is_missing(raw_artifacts):
            return []

        if not isinstance(raw_artifacts, list):
            raise WorkflowStateValidationError("code_artifacts must be a list")

        try:
            artifacts = [
                CodeArtifact.model_validate(artifact)
                for artifact in raw_artifacts
            ]
        except ValidationError as exc:
            raise WorkflowStateValidationError(
                "Workflow contains an invalid code artifact"
            ) from exc

        artifact_paper_ids = [
            artifact.paper_id
            for artifact in artifacts
        ]

        if len(artifact_paper_ids) != len(set(artifact_paper_ids)):
            raise WorkflowStateValidationError(
                "Code artifacts must have unique paper ids"
            )

        selected_id_set = set(selected_paper_ids)
        artifact_id_set = set(artifact_paper_ids)

        if artifact_id_set != selected_id_set:
            missing_ids = sorted(selected_id_set - artifact_id_set)
            unexpected_ids = sorted(
                artifact_id_set - selected_id_set
            )
            raise WorkflowStateValidationError(
                "Code artifact paper ids do not match selection; "
                f"missing={missing_ids}, unexpected={unexpected_ids}"
            )

        return artifacts
    
    
    
    @classmethod
    def _validate_reports(
        cls,
        values: Mapping[str, object],
        literature_run_id: int,
        artifacts: list[CodeArtifact],
    ) -> list[ValidationReport]:
        raw_reports = values.get("validation_reports")

        if cls._is_missing(raw_reports):
            return []

        if not isinstance(raw_reports, list):
            raise WorkflowStateValidationError("validation_reports must be a list")

        try:
            reports = [
                ValidationReport.model_validate(report)
                for report in raw_reports
            ]
        except ValidationError as exc:
            raise WorkflowStateValidationError(
                "Workflow contains an invalid validation report"
            ) from exc

        report_paper_ids = [
            report.paper_id
            for report in reports
        ]

        if len(report_paper_ids) != len(set(report_paper_ids)):
            raise WorkflowStateValidationError(
                "Validation reports must have unique paper ids"
            )

        if any(
            report.literature_run_id != literature_run_id
            for report in reports
        ):
            raise WorkflowStateValidationError(
                "Validation report literature run id does not match workflow"
            )

        artifacts_by_paper_id = {
            artifact.paper_id: artifact
            for artifact in artifacts
        }

        if set(report_paper_ids) != set(artifacts_by_paper_id):
            raise WorkflowStateValidationError(
                "Validation report paper ids do not match code artifacts"
            )

        for report in reports:
            artifact = artifacts_by_paper_id[report.paper_id]

            if (
                report.artifact_origin is not artifact.origin
                or report.artifact_status is not artifact.status
            ):
                raise WorkflowStateValidationError(
                    "Validation report artifact metadata does not "
                    f"match paper {report.paper_id}"
                )

        return reports

    @classmethod
    def _validate_failure(
        cls,
        values: Mapping[str, object],
    ) -> WorkflowFailure | None:
        raw_failure = values.get("failure")

        if cls._is_missing(raw_failure):
            return None

        try:
            return WorkflowFailure.model_validate(raw_failure)
        except ValidationError as exc:
            raise WorkflowStateValidationError(
                "Workflow contains invalid failure information"
            ) from exc
