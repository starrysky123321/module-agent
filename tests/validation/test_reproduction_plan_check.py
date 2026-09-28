import asyncio

import pytest

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
    ReproductionPlan,
)
from module_agent.validation.application.checks.reproduction_plan import (
    ReproductionPlanCheck,
)
from module_agent.validation.domain.report import (
    ValidationCheckKind,
    ValidationCheckStatus,
)


def make_reproduction_artifact(
    *,
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    open_questions: list[str] | None = None,
    warnings: list[str] | None = None,
) -> CodeArtifact:
    return CodeArtifact(
        paper_id=1,
        origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
        status=CodeArtifactStatus.REPRODUCTION_PLANNED,
        reproduction_plan=ReproductionPlan(
            research_problem="Reproduce the paper method",
            implementation_steps=["Implement the core algorithm"],
            inputs=inputs if inputs is not None else ["input tensor"],
            outputs=outputs if outputs is not None else ["output tensor"],
            open_questions=open_questions or [],
            warnings=warnings or [],
        ),
    )


def test_reproduction_check_supports_only_reproduction_plan() -> None:
    check = ReproductionPlanCheck()
    failed_artifact = CodeArtifact(
        paper_id=2,
        origin=CodeArtifactOrigin.UNKNOWN,
        status=CodeArtifactStatus.FAILED,
        error="Code preparation failed",
    )

    assert check.supports(make_reproduction_artifact()) is True
    assert check.supports(failed_artifact) is False


def test_reproduction_check_passes_complete_plan() -> None:
    result = asyncio.run(
        ReproductionPlanCheck().run(make_reproduction_artifact())
    )

    assert result.kind is ValidationCheckKind.REPRODUCTION_PLAN
    assert result.status is ValidationCheckStatus.PASSED
    assert result.details["implementation_step_count"] == 1
    assert result.details["missing_recommended"] == []


@pytest.mark.parametrize(
    ("inputs", "outputs", "missing_section"),
    [([], ["output tensor"], "inputs"), (["input tensor"], [], "outputs")],
)
def test_reproduction_check_warns_when_recommended_section_is_missing(
    inputs: list[str],
    outputs: list[str],
    missing_section: str,
) -> None:
    result = asyncio.run(
        ReproductionPlanCheck().run(
            make_reproduction_artifact(inputs=inputs, outputs=outputs)
        )
    )

    assert result.status is ValidationCheckStatus.WARNING
    assert missing_section in result.details["missing_recommended"]


@pytest.mark.parametrize(
    ("open_questions", "warnings"),
    [(["Which normalization should be used?"], []), ([], ["Dataset unavailable"])],
)
def test_reproduction_check_warns_about_unresolved_risks(
    open_questions: list[str],
    warnings: list[str],
) -> None:
    result = asyncio.run(
        ReproductionPlanCheck().run(
            make_reproduction_artifact(
                open_questions=open_questions,
                warnings=warnings,
            )
        )
    )

    assert result.status is ValidationCheckStatus.WARNING
    assert result.summary == "Reproduction plan requires clarification"


def test_reproduction_check_fails_when_plan_is_missing() -> None:
    malformed_artifact = CodeArtifact.model_construct(
        paper_id=1,
        origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
        status=CodeArtifactStatus.REPRODUCTION_PLANNED,
        reproduction_plan=None,
    )

    result = asyncio.run(ReproductionPlanCheck().run(malformed_artifact))

    assert result.status is ValidationCheckStatus.FAILED
    assert result.summary == "Reproduction artifact has no reproduction plan"


@pytest.mark.parametrize(
    ("research_problem", "implementation_steps", "missing_section"),
    [
        ("", ["Implement method"], "research_problem"),
        ("Problem", [], "implementation_steps"),
        ("Problem", [""], "implementation_steps"),
    ],
)
def test_reproduction_check_fails_when_required_section_is_missing(
    research_problem: str,
    implementation_steps: list[str],
    missing_section: str,
) -> None:
    malformed_plan = ReproductionPlan.model_construct(
        research_problem=research_problem,
        implementation_steps=implementation_steps,
        inputs=["input"],
        outputs=["output"],
        suggested_dependencies=[],
        open_questions=[],
        warnings=[],
    )
    malformed_artifact = CodeArtifact.model_construct(
        paper_id=1,
        origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
        status=CodeArtifactStatus.REPRODUCTION_PLANNED,
        reproduction_plan=malformed_plan,
    )

    result = asyncio.run(ReproductionPlanCheck().run(malformed_artifact))

    assert result.status is ValidationCheckStatus.FAILED
    assert missing_section in result.details["missing_required"]
