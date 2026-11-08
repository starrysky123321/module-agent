"""HTTP access to workflow child jobs; no execution inside request handlers."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response

from module_agent.experiments.jobs import PilotApproval, PilotJob, PilotRequest
from module_agent.shared.database.session import async_session_factory
from module_agent.workflow.experiments import WorkflowExperimentService

experiment_router = APIRouter(tags=["experiments"])


def get_experiment_service() -> WorkflowExperimentService:
    return WorkflowExperimentService(async_session_factory)


Service = Annotated[WorkflowExperimentService, Depends(get_experiment_service)]
RunId = Annotated[int, Path(gt=0)]


@experiment_router.get("/workflow/runs/{run_id}/experiments")
async def experiments(run_id: RunId, service: Service) -> dict:
    return await service.overview(run_id)


@experiment_router.post("/workflow/runs/{run_id}/experiments", response_model=PilotJob, status_code=201)
async def propose(run_id: RunId, request: PilotRequest, service: Service) -> PilotJob:
    return await service.propose(run_id, request)


@experiment_router.post("/experiments/{job_id}/confirm", response_model=PilotJob)
async def confirm(job_id: UUID, request: PilotApproval, service: Service) -> PilotJob:
    return await service.confirm(job_id, request)


@experiment_router.post("/experiments/{job_id}/cancel", response_model=PilotJob)
async def cancel(job_id: UUID, service: Service) -> PilotJob:
    return await service.cancel(job_id)


@experiment_router.get("/experiments/{job_id}/artifacts/{name}")
async def download(job_id: UUID, name: Annotated[str, Path(pattern=r"^[a-zA-Z0-9_.-]{1,80}$")], service: Service) -> Response:
    artifact = await service.artifact(job_id, name)
    return Response(artifact.content, media_type="application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="{artifact.name}"',
        "X-Content-SHA256": artifact.sha256, "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    })
