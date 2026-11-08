"""Optional experiment continuation of a selected, completed literature workflow."""

from datetime import datetime, timedelta, timezone
from secrets import compare_digest
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from module_agent.experiments.database import ExperimentArtifactModel, ExperimentJobModel, ExperimentWorkerModel
from module_agent.experiments.jobs import ACTIVE, PilotApproval, PilotJob, PilotProposal, PilotRequest
from module_agent.experiments.recipe import TITLE
from module_agent.literature.adapters.database.models.paper import PaperModel
from module_agent.literature.adapters.database.models.run import LiteratureRunModel, LiteratureRunPaperModel
from module_agent.literature.adapters.database.models.selection import PaperSelectionModel
from module_agent.shared.exceptions import AppException
from module_agent.shared.resources import ResourceSnapshot
from module_agent.workflow.adapters.database.model import ModuleWorkflowRunModel


def problem(message: str, status: int = 409) -> AppException:
    return AppException(message, code="experiment_unavailable", status_code=status)


def supports_paper(paper: PaperModel) -> bool:
    """An exact curated paper identity, never a keyword/any-MNIST match."""
    import re
    from urllib.parse import urlsplit

    if " ".join(paper.title.casefold().split()).rstrip(".") == TITLE.casefold():
        return True
    for identifier in (paper.doi, paper.landing_page_url, paper.pdf_url):
        value = str(identifier or "").lower()
        if re.fullmatch(r"10\.48550/arxiv\.2008\.10400(?:v\d+)?", value):
            return True
        try:
            url = urlsplit(value)
            if url.hostname in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"} and re.fullmatch(r"/(?:abs|pdf)/2008\.10400(?:v\d+)?(?:\.pdf)?", url.path):
                return True
            if url.hostname == "doi.org" and re.fullmatch(r"/10\.48550/arxiv\.2008\.10400(?:v\d+)?", url.path):
                return True
        except ValueError:
            continue
    return False


class WorkflowExperimentService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def _parent(self, session: AsyncSession, run_id: int) -> ModuleWorkflowRunModel:
        parent = await session.scalar(select(LiteratureRunModel).where(LiteratureRunModel.id == run_id).with_for_update())
        if parent is None:
            raise problem("任务不存在。", 404)
        workflow = await session.get(ModuleWorkflowRunModel, run_id)
        if workflow is None or workflow.status != "completed":
            raise problem("请先完成论文选择、代码获取和静态验证流程。")
        return workflow

    async def _eligible(self, session: AsyncSession, run_id: int) -> list[PaperModel]:
        selection = await session.get(PaperSelectionModel, run_id)
        if selection is None:
            return []
        rows = (await session.execute(
            select(PaperModel, LiteratureRunPaperModel.integrity)
            .join(LiteratureRunPaperModel, LiteratureRunPaperModel.paper_id == PaperModel.id)
            .where(LiteratureRunPaperModel.run_id == run_id, PaperModel.id.in_(selection.selected_paper_ids))
        )).all()
        return [paper for paper, integrity in rows if supports_paper(paper)
                and (integrity or {}).get("status") not in {"retracted", "notice"}]

    async def _reap(self, session: AsyncSession) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=90)
        alive = select(ExperimentWorkerModel.id).where(ExperimentWorkerModel.heartbeat_at >= cutoff)
        await session.execute(update(ExperimentJobModel).where(
            ExperimentJobModel.status.in_(ACTIVE), ExperimentJobModel.worker_id.not_in(alive),
            ExperimentJobModel.updated_at < cutoff,
        ).values(status="interrupted", stage="interrupted", error="实验 Worker 已失联；不自动重跑。请检查执行机，再创建新计划。"))

    async def overview(self, run_id: int) -> dict:
        async with self.sessions() as session, session.begin():
            if await session.get(LiteratureRunModel, run_id) is None:
                raise problem("任务不存在。", 404)
            await self._reap(session)
            workflow = await session.get(ModuleWorkflowRunModel, run_id)
            eligible = await self._eligible(session, run_id) if workflow and workflow.status == "completed" else []
            workers = (await session.scalars(select(ExperimentWorkerModel).where(
                ExperimentWorkerModel.heartbeat_at >= datetime.now(timezone.utc) - timedelta(seconds=30)
            ))).all()
            jobs = (await session.scalars(select(ExperimentJobModel).where(
                ExperimentJobModel.literature_run_id == run_id
            ).order_by(ExperimentJobModel.created_at.desc()).limit(20))).all()
            return {
                "eligible_papers": [{"id": p.id, "title": p.title} for p in eligible],
                "workers": [{"id": w.id, "resources": w.resources, "heartbeat_at": w.heartbeat_at} for w in workers],
                "jobs": [await self._view(session, job) for job in jobs],
                "notice": "目前只支持 arXiv:2008.10400 的 M5/MNIST 两轮试跑，其他论文尚不支持真实实验。",
            }

    async def _worker(self, session: AsyncSession, proposal: PilotProposal) -> None:
        worker = await session.get(ExperimentWorkerModel, proposal.worker_id)
        if worker is None or worker.heartbeat_at < datetime.now(timezone.utc) - timedelta(seconds=30):
            raise problem("实验 Worker 不在线，请启动独立 Worker 后重试。")
        resources = ResourceSnapshot.model_validate(worker.resources)
        budget = proposal.budget
        if not resources.sandbox_ready or budget.gpu_uuid not in {g.uuid for g in resources.gpus}:
            raise problem("执行机的 Docker 或所选 GPU 不可用，请重新检测。")
        if budget.cpu_limit > resources.available_cpu_count or budget.memory_mb > (resources.memory_available_mb or 0):
            raise problem("预算超出执行机当前可用 CPU 或内存，请减少预算。")
        if (resources.workspace_free_mb or 0) < budget.output_mb + 1024:
            raise problem("执行机剩余磁盘不足，请释放空间。镜像缓存另需约 16 GB。")
        if budget.timeout_seconds > 900 or budget.output_mb > 4096:
            raise problem("试跑最多允许 900 秒、4096 MB 输出空间。")

    async def propose(self, run_id: int, request: PilotRequest) -> PilotJob:
        async with self.sessions() as session, session.begin():
            await self._parent(session, run_id)
            if request.paper_id not in {p.id for p in await self._eligible(session, run_id)}:
                raise problem("该论文不在已选择的受支持论文中，不能套用 M5 实验方案。")
            proposal = PilotProposal(literature_run_id=run_id, **request.model_dump())
            await self._worker(session, proposal)
            job = ExperimentJobModel(id=proposal.id, literature_run_id=run_id, paper_id=request.paper_id,
                                     worker_id=request.worker_id, proposal=proposal.model_dump(mode="json"))
            session.add(job)
            await session.flush()
            return await self._view(session, job)

    async def _job(self, session: AsyncSession, job_id: UUID) -> ExperimentJobModel:
        job = await session.scalar(select(ExperimentJobModel).where(ExperimentJobModel.id == job_id).with_for_update())
        if job is None:
            raise problem("实验不存在。", 404)
        return job

    async def confirm(self, job_id: UUID, approval: PilotApproval) -> PilotJob:
        try:
            async with self.sessions() as session, session.begin():
                # Lock parent before child, matching task deletion lock order.
                parent_id = await session.scalar(select(ExperimentJobModel.literature_run_id).where(ExperimentJobModel.id == job_id))
                if parent_id is None:
                    raise problem("实验不存在。", 404)
                await self._parent(session, parent_id)
                job = await self._job(session, job_id)
                proposal = PilotProposal.model_validate(job.proposal)
                if not compare_digest(proposal.digest(), approval.proposal_sha256):
                    raise problem("确认内容与冻结计划不一致，请重新生成计划。")
                if job.status != "draft":
                    if job.consent == approval.model_dump(mode="json"):
                        return await self._view(session, job)  # Network retries never queue twice.
                    raise problem("计划已确认或结束，不能再次执行。")
                if job.paper_id not in {p.id for p in await self._eligible(session, parent_id)}:
                    raise problem("所选论文已变化，不能执行旧计划。")
                await self._worker(session, proposal)
                job.consent = approval.model_dump(mode="json")
                job.status, job.stage = "queued", "queued"
                await session.flush()
                return await self._view(session, job)
        except IntegrityError as error:
            raise problem("这篇论文已有排队或执行中的实验，请勿重复提交。") from error

    async def cancel(self, job_id: UUID) -> PilotJob:
        async with self.sessions() as session, session.begin():
            job = await self._job(session, job_id)
            if job.status in {"draft", "queued"}:
                job.status, job.stage = "cancelled", "cancelled"
            elif job.status in ACTIVE:
                job.status = "cancelling"
            await session.flush()
            return await self._view(session, job)

    async def _view(self, session: AsyncSession, job: ExperimentJobModel) -> PilotJob:
        names = list((await session.scalars(select(ExperimentArtifactModel.name).where(ExperimentArtifactModel.job_id == job.id))).all())
        proposal = PilotProposal.model_validate(job.proposal)
        return PilotJob(id=job.id, literature_run_id=job.literature_run_id, paper_id=job.paper_id,
                        status=job.status, stage=job.stage, proposal=proposal, proposal_sha256=proposal.digest(),
                        created_at=job.created_at, updated_at=job.updated_at, log_tail=job.log_tail,
                        error=job.error, result=job.result, artifacts=names)

    async def artifact(self, job_id: UUID, name: str) -> ExperimentArtifactModel:
        async with self.sessions() as session:
            artifact = await session.get(ExperimentArtifactModel, (job_id, name))
            if artifact is None:
                raise problem("该实验产物尚不存在。", 404)
            return artifact
