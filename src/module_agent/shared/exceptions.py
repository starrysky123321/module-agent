from typing import Any


class AppException(Exception):
    """封装 AppException 相关的数据和行为。"""
    def __init__(
        self,
        message: str,
        code: str,
        status_code: int = 400,
        details: Any = None,
    ) -> None:
        """初始化当前对象。"""
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class LiteratureRunNotFoundError(Exception):
    """表示该业务场景的异常。"""
    def __init__(self, run_id: int) -> None:
        """初始化当前对象。"""
        self.run_id = run_id
        super().__init__(f"Run with id {run_id} not found")


class LiteratureRunStateError(ValueError):
    """表示该业务场景的异常。"""
    def __init__(self, run_id: int, action: str) -> None:
        """初始化当前对象。"""
        self.run_id = run_id
        self.action = action
        super().__init__(
            f"Run with id {run_id} is not in a valid state to {action}"
        )


class LiteratureSourceSkippedError(RuntimeError):
    """Raised when a source call is intentionally skipped without an HTTP call."""

class PaperSelectionAlreadyExistsError(AppException):
    """表示该业务场景的异常。"""
    def __init__(self, run_id: int) -> None:
        """初始化当前对象。"""
        self.run_id = run_id
        super().__init__(
            message=f"Paper selection for run {run_id} already exists",
            code="paper_selection_already_exists",
            status_code=409,
        )
        

class InvalidPaperSelectionError(AppException):
    """表示该业务场景的异常。"""
    def __init__(
        self,
        run_id: int,
        invalid_paper_ids: list[int],
    ) -> None:
        """初始化当前对象。"""
        self.run_id = run_id
        self.invalid_paper_ids = list(invalid_paper_ids)
        super().__init__(
            message=(
                f"Papers {self.invalid_paper_ids} do not belong "
                f"to literature run {run_id}"
            ),
            code="invalid_paper_selection",
            status_code=422,
            details={
                "run_id": run_id,
                "invalid_paper_ids": self.invalid_paper_ids,
            },
        )
        

class WorkflowAlreadyProgressedError(AppException):
    """表示该业务场景的异常。"""
    def __init__(self, run_id: int) -> None:
        """初始化当前对象。"""
        self.run_id = run_id
        super().__init__(
            message=(
                f"Workflow for literature run {run_id} "
                "has already progressed"
            ),
            code="workflow_already_progressed",
            status_code=409,
        )
        

class WorkflowNotWaitingForSelectionError(AppException):
    """表示该业务场景的异常。"""
    def __init__(self, run_id: int) -> None:
        """初始化当前对象。"""
        self.run_id = run_id
        super().__init__(
            message=(
                f"Workflow for literature run {run_id} "
                "is not waiting for paper selection"
            ),
            code="workflow_not_waiting_for_selection",
            status_code=409,
        )


class WorkflowNotWaitingForLiteratureError(AppException):
    """表示该业务场景的异常。"""
    def __init__(self, run_id: int) -> None:
        """初始化当前对象。"""
        self.run_id = run_id
        super().__init__(
            message=(
                f"Workflow for literature run {run_id} "
                "is not waiting for literature completion"
            ),
            code="workflow_not_waiting_for_literature",
            status_code=409,
        )
        
    
class WorkflowResultNotReadyError(AppException):
    """表示该业务场景的异常。"""
    def __init__(
        self,
        run_id: int,
        status: str | None,
    ) -> None:
        """初始化当前对象。"""
        self.run_id = run_id
        self.status = status

        super().__init__(
            message=(
                f"Workflow result for literature run {run_id} "
                "is not ready"
            ),
            code="workflow_result_not_ready",
            status_code=409,
            details={
                "run_id": run_id,
                "status": status,
            },
        )


class CodeRunNotFoundError(AppException):
    """表示该业务场景的异常。"""
    def __init__(self, run_id: int) -> None:
        """初始化当前对象。"""
        super().__init__(
            message=f"CodeRun {run_id} not found",
            code="code_run_not_found",
            status_code=404,
            details={"run_id": run_id},
        )


class ValidationRunNotFoundError(AppException):
    """表示该业务场景的异常。"""
    def __init__(self, run_id: int) -> None:
        """初始化当前对象。"""
        super().__init__(
            message=f"ValidationRun {run_id} not found",
            code="validation_run_not_found",
            status_code=404,
            details={"run_id": run_id},
        )


class WorkflowLifecycleNotFoundError(AppException):
    """表示该业务场景的异常。"""
    def __init__(self, run_id: int) -> None:
        """初始化当前对象。"""
        super().__init__(
            message=f"Workflow lifecycle for run {run_id} not found",
            code="workflow_lifecycle_not_found",
            status_code=404,
            details={"run_id": run_id},
        )


class WorkflowControlError(AppException):
    """表示该业务场景的异常。"""
    def __init__(self, run_id: int, reason: str) -> None:
        """初始化当前对象。"""
        super().__init__(
            message=f"Workflow {run_id} control request rejected: {reason}",
            code="workflow_control_rejected",
            status_code=409,
            details={"run_id": run_id, "reason": reason},
        )
