"""Public experiment contracts: approval precedes all network/code execution."""

from datetime import datetime
import hashlib
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field

from module_agent.experiments.domain import ExperimentBudget, FrozenModel, Sha256
from module_agent.experiments.recipe import RECIPE_SHA256

ACTIVE = ("queued", "preparing", "running", "cancelling")
TERMINAL = ("completed", "failed", "timed_out", "cancelled", "interrupted")


class PilotRequest(FrozenModel):
    paper_id: int = Field(gt=0)
    worker_id: UUID
    budget: ExperimentBudget


class PilotProposal(FrozenModel):
    id: UUID = Field(default_factory=uuid4)
    literature_run_id: int
    paper_id: int
    worker_id: UUID
    budget: ExperimentBudget
    recipe: Literal["mnist-m5-pilot-v1"] = "mnist-m5-pilot-v1"
    recipe_sha256: Sha256 = RECIPE_SHA256
    source_commit: Literal["a21bd677f62fcdee77c82419b898d421682e3fd2"] = "a21bd677f62fcdee77c82419b898d421682e3fd2"
    seed: Literal[0] = 0
    epochs: Literal[2] = 2
    train_samples: Literal[60000] = 60000
    test_samples: Literal[10000] = 10000
    preparation_timeout_seconds: Literal[1200] = 1200
    image_cache_estimate_mb: Literal[16384] = 16384
    notice: str = "单模型、单种子、2 轮试跑，不等于论文复现。准备阶段会联网下载固定源码、MNIST 和镜像（缓存约 16 GB，非硬限额）；训练容器断网。源码未发现许可证，请自行确认使用权限；GPU 显存没有硬限额。"

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class PilotApproval(FrozenModel):
    proposal_sha256: Sha256
    execute_code: Literal[True]
    allow_preparation_network: Literal[True]
    acknowledge_source_license: Literal[True]
    acknowledge_gpu_not_memory_capped: Literal[True]


class PilotJob(FrozenModel):
    id: UUID
    literature_run_id: int
    paper_id: int
    status: str
    stage: str
    proposal: PilotProposal
    proposal_sha256: Sha256
    created_at: datetime
    updated_at: datetime
    log_tail: str = ""
    error: str | None = None
    result: dict[str, object] | None = None
    artifacts: list[str] = Field(default_factory=list)
    paper_reproduced: Literal[False] = False
