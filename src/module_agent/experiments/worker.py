"""Dedicated host-side GPU worker. Database queue claims never replay training."""

import asyncio
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from module_agent.experiments.database import ExperimentArtifactModel, ExperimentJobModel, ExperimentWorkerModel
from module_agent.experiments.docker import DockerExperimentRunner
from module_agent.experiments.domain import ExperimentConsent, ExperimentPlan
from module_agent.experiments.jobs import PilotApproval, PilotProposal
from module_agent.experiments.preparation import command, prepare_m5
from module_agent.experiments.recipe import RECIPE_SHA256
from module_agent.experiments.service import ExperimentService
from module_agent.experiments.workspace import ExperimentWorkspace, bounded_read
from module_agent.shared.execution_control import ExecutionStopped, run_with_control
from module_agent.shared.redaction import redact_sensitive_text as redact_secrets
from module_agent.shared.resources import inspect_resources


class ExperimentWorker:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], root: Path, image: str = "") -> None:
        self.sessions, self.root, self.image = sessions, root.resolve(), image
        self.id = uuid4()  # A restarted process cannot reclaim an old training job.
        self.current: UUID | None = None
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    async def heartbeat(self) -> None:
        snapshot = await asyncio.to_thread(inspect_resources, self.root)
        try:
            runtimes = await command("docker", "info", "--format", "{{json .Runtimes}}", timeout=5)
            snapshot.sandbox_ready = '"nvidia"' in runtimes
            snapshot.sandbox_reason = "执行机 Docker 已连接；CUDA 内核将在批准后验证。" if snapshot.sandbox_ready else "Docker 未配置 NVIDIA runtime。"
        except (OSError, RuntimeError, TimeoutError):
            snapshot.sandbox_ready, snapshot.sandbox_reason = False, "执行机 Docker 未就绪。"
        async with self.sessions() as session, session.begin():
            await session.execute(insert(ExperimentWorkerModel).values(
                id=self.id, resources=snapshot.model_dump(mode="json"), heartbeat_at=datetime.now(timezone.utc),
            ).on_conflict_do_update(index_elements=[ExperimentWorkerModel.id], set_={
                "resources": snapshot.model_dump(mode="json"), "heartbeat_at": datetime.now(timezone.utc),
            }))

    async def claim(self) -> PilotProposal | None:
        async with self.sessions() as session, session.begin():
            job = await session.scalar(select(ExperimentJobModel).where(
                ExperimentJobModel.worker_id == self.id, ExperimentJobModel.status == "queued",
            ).order_by(ExperimentJobModel.created_at).with_for_update(skip_locked=True).limit(1))
            if job is None:
                return None
            proposal = PilotProposal.model_validate(job.proposal)
            approval = PilotApproval.model_validate(job.consent)
            if approval.proposal_sha256 != proposal.digest() or proposal.recipe_sha256 != RECIPE_SHA256:
                job.status, job.error = "failed", "授权记录与实验计划不一致。"
                return None
            job.status, job.stage = "preparing", "preparing"
            return proposal

    async def allowed(self) -> bool:
        async with self.sessions() as session:
            status = await session.scalar(select(ExperimentJobModel.status).where(ExperimentJobModel.id == self.current))
            return status in {"preparing", "running"}

    async def publish(self, **values: object) -> None:
        async with self.sessions() as session, session.begin():
            job = await session.scalar(select(ExperimentJobModel).where(
                ExperimentJobModel.id == self.current,
                ExperimentJobModel.worker_id == self.id,
                ExperimentJobModel.status.in_(("preparing", "running", "cancelling")),
            ).with_for_update())
            if job is None:
                return
            if job.status == "cancelling" and values.get("status") == "running":
                return
            if job.status == "cancelling" and values.get("status") == "completed":
                values.update(status="cancelled", stage="cancelled", error="实验在收集结果时收到停止请求；已保留结果。")
            for key, value in values.items():
                setattr(job, key, value)

    async def progress(self, plan: ExperimentPlan) -> None:
        workspace = ExperimentWorkspace(self.root)
        directory = workspace.run_directory(plan)
        while True:
            try:
                import json

                result = json.loads(bounded_read(directory / "result.json", 2_000_000))
                log = bounded_read(directory / "execution.log", 1_100_000).decode(errors="replace")
                await self.publish(stage=result["stage"], log_tail=redact_secrets(log[-32000:]))
            except FileNotFoundError:
                pass
            await asyncio.sleep(1)

    async def evidence(self, plan: ExperimentPlan) -> None:
        directory = ExperimentWorkspace(self.root).run_directory(plan)
        filenames = {
            "plan.json": "plan.json", "consent.json": "consent.json", "result.json": "result.json",
            "metrics.json": "metrics.json", "environment.json": "environment.json", "execution.log": "execution.log",
            "training-log.txt": "outputs/pilot/log000.out", "wrong-indices.txt": "outputs/pilot/wrong000.txt",
            "weights.pth": "outputs/pilot/model000.pth",
        }
        records = []
        for name, relative in filenames.items():
            path = directory / relative
            if not path.exists():
                continue
            data = bounded_read(path, 16_000_000)
            # Results and logs can contain source paths, but never credentials.
            if name != "weights.pth":
                data = redact_secrets(data.decode(errors="replace")).encode()
            records.append(ExperimentArtifactModel(job_id=plan.id, name=name,
                           sha256=hashlib.sha256(data).hexdigest(), content=data))
        async with self.sessions() as session, session.begin():
            for record in records:
                await session.execute(insert(ExperimentArtifactModel).values(
                    job_id=record.job_id, name=record.name, sha256=record.sha256, content=record.content,
                ).on_conflict_do_nothing())

    async def execute(self, proposal: PilotProposal) -> None:
        self.current = proposal.id
        plan = None
        try:
            async def operation() -> None:
                nonlocal plan
                async with asyncio.timeout(proposal.preparation_timeout_seconds):
                    plan = await prepare_m5(self.root, proposal, self.image)
                if not await self.allowed():
                    raise ExecutionStopped()
                await self.publish(status="running", stage="environment", plan=plan.model_dump(mode="json"))
                consent = ExperimentConsent(plan_sha256=plan.digest(), execute_code=True,
                    acknowledge_source_license=True, acknowledge_gpu_not_memory_capped=True)
                service = ExperimentService(ExperimentWorkspace(self.root), DockerExperimentRunner(ExperimentWorkspace(self.root)))
                progress = asyncio.create_task(self.progress(plan))
                try:
                    result = await service.execute(plan, consent)
                finally:
                    progress.cancel()
                    await asyncio.gather(progress, return_exceptions=True)
                # Persist/download evidence before declaring success.
                await self.evidence(plan)
                await self.publish(status=result.status.value, stage=result.stage,
                                   result=result.model_dump(mode="json"), error=result.error)

            await run_with_control(operation, self.allowed, poll_seconds=0.5)
        except (ExecutionStopped, asyncio.CancelledError):
            if plan is not None:
                await self.evidence(plan)
            await self.publish(status="cancelled", stage="cancelled", error="实验已停止，已有产物保留；不自动重跑。")
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise
        except TimeoutError:
            await self.publish(status="timed_out", stage="timed_out", error="环境或数据准备超过 20 分钟，已停止；不自动重跑。")
        except Exception as error:
            await self.publish(status="failed", stage="failed", error="实验失败，诊断信息：" + redact_secrets(str(error))[:1000])
        finally:
            self.current = None

    async def run(self) -> None:
        # A second process cannot prepare into, or execute from, this same cache.
        with ExperimentWorkspace(self.root).execution_lock(worker=True):
            await self._run()

    async def _run(self) -> None:
        async def pulse() -> None:
            while True:
                await self.heartbeat()
                await asyncio.sleep(5)

        await self.heartbeat()
        print(f"实验 Worker 已上线：{self.id}；仅执行网页明确确认的 M5 试跑。", flush=True)
        heartbeat = asyncio.create_task(pulse())
        try:
            while True:
                # A failed heartbeat must stop active code rather than silently losing ownership.
                if heartbeat.done():
                    heartbeat.result()
                if proposal := await self.claim():
                    execution = asyncio.create_task(self.execute(proposal))
                    try:
                        done, _ = await asyncio.wait((execution, heartbeat), return_when=asyncio.FIRST_COMPLETED)
                        if heartbeat in done:
                            heartbeat.result()
                        await execution
                    finally:
                        if not execution.done():
                            execution.cancel()
                            await asyncio.gather(execution, return_exceptions=True)
                else:
                    await asyncio.sleep(1)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            async with self.sessions() as session, session.begin():
                await session.execute(update(ExperimentWorkerModel).where(ExperimentWorkerModel.id == self.id).values(
                    heartbeat_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
                ))
