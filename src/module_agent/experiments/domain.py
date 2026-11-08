"""Frozen experiment inputs, budgets, authorization and honest result states."""

from enum import StrEnum
import hashlib
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ImageReference = Annotated[
    str,
    StringConstraints(
        pattern=r"^(?:[a-zA-Z0-9][a-zA-Z0-9._/:\-]*@)?sha256:[0-9a-f]{64}$"
    ),
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ExperimentBudget(FrozenModel):
    """Runtime caps; a GPU selector is not a VRAM reservation or memory cap."""

    cpu_limit: float = Field(default=2, gt=0, le=8)
    memory_mb: int = Field(default=4096, ge=256, le=16384)
    output_mb: int = Field(default=2048, ge=16, le=65536)
    temporary_mb: int = Field(default=512, ge=16, le=16384)
    timeout_seconds: int = Field(default=900, ge=1, le=86400)
    gpu_uuid: Annotated[str, StringConstraints(pattern=r"^GPU-[a-zA-Z0-9-]{1,100}$")]


class ExperimentPlan(FrozenModel):
    """Only a short M5 pilot is currently supported, not an ensemble benchmark."""

    id: UUID = Field(default_factory=uuid4)
    case_id: Literal["mnist-m5-pilot-v1"] = "mnist-m5-pilot-v1"
    paper_id: Literal["2008.10400v2"] = "2008.10400v2"
    source_commit: Literal["a21bd677f62fcdee77c82419b898d421682e3fd2"] = (
        "a21bd677f62fcdee77c82419b898d421682e3fd2"
    )
    repository_path: Path
    dataset_path: Path
    source_sha256: Sha256
    dataset_sha256: Sha256
    image: ImageReference
    budget: ExperimentBudget
    seed: int = Field(default=0, ge=0, le=2**31 - 1)
    epochs: int = Field(default=2, ge=1, le=2)
    source_patch_note: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    purpose: Literal["pilot_not_paper_reproduction"] = "pilot_not_paper_reproduction"

    @model_validator(mode="after")
    def absolute_inputs(self) -> "ExperimentPlan":
        if (
            not self.repository_path.is_absolute()
            or not self.dataset_path.is_absolute()
        ):
            raise ValueError("Experiment paths must be absolute")
        return self

    def digest(self) -> str:
        """Bind consent to every input, image, patch description and budget."""
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class ExperimentConsent(FrozenModel):
    plan_sha256: Sha256
    execute_code: Literal[True]
    acknowledge_source_license: Literal[True]
    acknowledge_gpu_not_memory_capped: Literal[True]


class ExperimentStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class StepResult(FrozenModel):
    name: Literal["environment", "train", "evaluate"]
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = Field(ge=0)
    output_truncated: bool = False


class ExperimentMetrics(FrozenModel):
    """Counts, not a success log line, are the basis of the pilot report."""

    evaluated_samples: Literal[10000] = 10000
    correct: int = Field(ge=0, le=10000)
    wrong: int = Field(ge=0, le=10000)
    accuracy_percent: float = Field(ge=0, le=100)
    completed_epochs: int = Field(ge=1, le=2)
    checkpoint_sha256: Sha256

    @model_validator(mode="after")
    def consistent_counts(self) -> "ExperimentMetrics":
        if self.correct + self.wrong != self.evaluated_samples:
            raise ValueError("Test counts do not add up")
        if (
            abs(self.accuracy_percent - self.correct / self.evaluated_samples * 100)
            > 1e-8
        ):
            raise ValueError("Accuracy does not match sample counts")
        return self


class ExperimentResult(FrozenModel):
    plan_id: UUID
    plan_sha256: Sha256
    status: ExperimentStatus
    stage: str
    steps: tuple[StepResult, ...] = ()
    metrics: ExperimentMetrics | None = None
    error: str | None = None
    paper_reproduced: Literal[False] = False
    comparison: Literal["not_comparable_short_single_seed_pilot"] = (
        "not_comparable_short_single_seed_pilot"
    )

    @model_validator(mode="after")
    def complete_requires_evidence(self) -> "ExperimentResult":
        if self.status is ExperimentStatus.COMPLETED and (
            self.metrics is None
            or self.error is not None
            or tuple(step.name for step in self.steps)
            != ("environment", "train", "evaluate")
            or any(step.exit_code != 0 for step in self.steps)
        ):
            raise ValueError(
                "Completed experiments require all steps and valid metrics"
            )
        return self
