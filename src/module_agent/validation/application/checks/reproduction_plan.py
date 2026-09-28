from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactStatus,
)
from module_agent.validation.domain.report import (
    ValidationCheck,
    ValidationCheckKind,
    ValidationCheckStatus,
)


class ReproductionPlanCheck:
    """检查复现计划是否具备必要结构和信息。"""

    @property
    def kind(self) -> ValidationCheckKind:
        """返回当前检查器的类型。"""
        return ValidationCheckKind.REPRODUCTION_PLAN

    def supports(self, artifact: CodeArtifact) -> bool:
        """判断当前检查器是否支持该产物。"""
        return artifact.status is CodeArtifactStatus.REPRODUCTION_PLANNED

    async def run(self, artifact: CodeArtifact) -> ValidationCheck:
        """执行当前任务。"""
        plan = artifact.reproduction_plan

        if plan is None:
            return ValidationCheck(
                kind=self.kind,
                status=ValidationCheckStatus.FAILED,
                summary="Reproduction artifact has no reproduction plan",
            )

        missing_required: list[str] = []
        if not plan.research_problem.strip():
            missing_required.append("research_problem")
        if not plan.implementation_steps or any(
            not step.strip() for step in plan.implementation_steps
        ):
            missing_required.append("implementation_steps")

        if missing_required:
            return ValidationCheck(
                kind=self.kind,
                status=ValidationCheckStatus.FAILED,
                summary="Reproduction plan is missing required sections",
                details={"missing_required": missing_required},
            )

        missing_recommended: list[str] = []

        if not plan.inputs:
            missing_recommended.append("inputs")
        if not plan.outputs:
            missing_recommended.append("outputs")

        requires_clarification = bool(
            missing_recommended
            or plan.open_questions
            or plan.warnings
        )
        status = (
            ValidationCheckStatus.WARNING
            if requires_clarification
            else ValidationCheckStatus.PASSED
        )
        summary = (
            "Reproduction plan requires clarification"
            if requires_clarification
            else "Reproduction plan is structurally complete"
        )
        details = {
            "implementation_step_count": len(plan.implementation_steps),
            "inputs": plan.inputs,
            "outputs": plan.outputs,
            "suggested_dependencies": plan.suggested_dependencies,
            "open_questions": plan.open_questions,
            "warnings": plan.warnings,
            "missing_required": missing_required,
            "missing_recommended": missing_recommended,
        }

        return ValidationCheck(
            kind=self.kind,
            status=status,
            summary=summary,
            details=details,
        )
