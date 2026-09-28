import asyncio
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

import httpx

from module_agent.literature.application.agent import LiteratureAgent
from module_agent.shared.exceptions import (
    InvalidPaperSelectionError,
    LiteratureRunNotFoundError,
    LiteratureRunStateError,
    PaperSelectionAlreadyExistsError,
    WorkflowAlreadyProgressedError,
)
from module_agent.bootstrap.api_dependencies import (
    get_literature_agent,
    get_literature_result_service,
    get_literature_run_dispatcher,
    get_literature_run_service,
    get_module_workflow_coordinator,
)
from module_agent.literature.domain.search import (
    LiteratureBundle,
    PaperSearchResult,
    SearchRequest,
)
from module_agent.literature.domain.run import LiteratureRun, LiteratureRunStatus
from module_agent.literature.domain.paper import Paper
from module_agent.literature.domain.selection import PaperSelection
from module_agent.workflow.domain import (
    LiteratureWaitInterrupt,
    PaperSelectionInterrupt,
)
from module_agent.literature.domain.recommendation import (
    LiteraturePaperRecommendation,
)
from module_agent.main import create_app
from module_agent.literature.application.result import LiteratureResultService
from module_agent.literature.application.run import LiteratureRunService
from module_agent.literature.application.dispatch import LiteratureRunDispatcher
from module_agent.workflow.coordinator import (
    ModuleWorkflowCoordinator,
)


def test_literature_api_runs_agent_and_returns_bundle() -> None:
    request = SearchRequest(
        topic="small object detection",
        description="搜索高质量小目标检测论文",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        venues=["CVPR"],
        keywords=[],
        exclusion_keywords=[],
        max_results=10,
    )
    paper = PaperSearchResult(
        source="openalex",
        source_id="W123",
        title="Example Paper",
        venue="CVPR",
        doi="10.1000/example",
    )
    bundle = LiteratureBundle(
        request=request,
        search_queries=["small object detection"],
        candidates=[paper],
        selected_papers=[paper],
    )
    agent = AsyncMock(spec=LiteratureAgent)
    agent.run.return_value = bundle
    application = create_app()
    application.dependency_overrides[get_literature_agent] = lambda: agent

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/literature/search",
                json=request.model_dump(mode="json"),
            )

    response = asyncio.run(send_request())

    assert response.status_code == 200
    assert response.json()["selected_papers"][0]["doi"] == "10.1000/example"
    agent.run.assert_awaited_once_with(request)


def test_literature_api_rejects_invalid_date_range() -> None:
    agent = AsyncMock(spec=LiteratureAgent)
    application = create_app()
    application.dependency_overrides[get_literature_agent] = lambda: agent

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/literature/search",
                json={
                    "topic": "object detection",
                    "description": "invalid dates",
                    "start_date": "2025-01-01",
                    "end_date": "2024-01-01",
                    "venues": [],
                    "keywords": [],
                    "exclusion_keywords": [],
                    "max_results": 10,
                },
            )

    response = asyncio.run(send_request())

    assert response.status_code == 422
    agent.run.assert_not_awaited()


def test_literature_api_creates_pending_run() -> None:
    request = SearchRequest(
        topic="small object detection",
        description="Create a durable literature task",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=["detection"],
        max_results=10,
    )
    created = LiteratureRun(
        id=8,
        status=LiteratureRunStatus.PENDING,
        request=request,
    )
    service = AsyncMock(spec=LiteratureRunService)
    service.create_run.return_value = created
    application = create_app()
    application.dependency_overrides[get_literature_run_service] = lambda: service

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/literature/runs",
                json=request.model_dump(mode="json"),
            )

    response = asyncio.run(send_request())

    assert response.status_code == 201
    assert response.json()["id"] == 8
    assert response.json()["status"] == "pending"
    service.create_run.assert_awaited_once_with(request)


def test_literature_api_gets_run() -> None:
    request = SearchRequest(
        topic="small object detection",
        description="Read a durable literature task",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=[],
        max_results=10,
    )
    run = LiteratureRun(id=8, request=request)
    service = AsyncMock(spec=LiteratureRunService)
    service.get_run.return_value = run
    application = create_app()
    application.dependency_overrides[get_literature_run_service] = lambda: service

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/api/literature/runs/8")

    response = asyncio.run(send_request())

    assert response.status_code == 200
    assert response.json()["id"] == 8
    service.get_run.assert_awaited_once_with(8)


def test_literature_api_maps_missing_run_to_404() -> None:
    service = AsyncMock(spec=LiteratureRunService)
    service.get_run.side_effect = LiteratureRunNotFoundError(99)
    application = create_app()
    application.dependency_overrides[get_literature_run_service] = lambda: service

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/api/literature/runs/99")

    response = asyncio.run(send_request())

    assert response.status_code == 404
    assert response.json() == {"detail": "Run with id 99 not found"}


def test_literature_api_enqueues_run() -> None:
    dispatcher = AsyncMock(spec=LiteratureRunDispatcher)
    dispatcher.dispatch.return_value = "message-123"
    application = create_app()
    application.dependency_overrides[get_literature_run_dispatcher] = (
        lambda: dispatcher
    )

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post("/api/literature/runs/8/enqueue")

    response = asyncio.run(send_request())

    assert response.status_code == 202
    assert response.json() == {
        "run_id": 8,
        "message_id": "message-123",
        "status": "queued",
    }
    dispatcher.dispatch.assert_awaited_once_with(8)


def test_literature_enqueue_maps_missing_run_to_404() -> None:
    dispatcher = AsyncMock(spec=LiteratureRunDispatcher)
    dispatcher.dispatch.side_effect = LiteratureRunNotFoundError(99)
    application = create_app()
    application.dependency_overrides[get_literature_run_dispatcher] = (
        lambda: dispatcher
    )

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post("/api/literature/runs/99/enqueue")

    response = asyncio.run(send_request())

    assert response.status_code == 404
    assert response.json() == {"detail": "Run with id 99 not found"}


def test_literature_enqueue_maps_state_conflict_to_409() -> None:
    dispatcher = AsyncMock(spec=LiteratureRunDispatcher)
    dispatcher.dispatch.side_effect = LiteratureRunStateError(8, "queue")
    application = create_app()
    application.dependency_overrides[get_literature_run_dispatcher] = (
        lambda: dispatcher
    )

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post("/api/literature/runs/8/enqueue")

    response = asyncio.run(send_request())

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Run with id 8 is not in a valid state to queue"
    }


def test_literature_api_gets_run_papers() -> None:
    papers = [
        LiteraturePaperRecommendation(
            id=20,
            source="openalex",
            source_id="W20",
            title="Selected Paper",
            authors=["Example Author"],
            doi="10.1000/example",
            is_open_access=True,
            position=0,
            relevance_score=0.95,
            relevance_reason="Directly addresses the requested problem",
            matched_terms=["oversmoothing"],
        )
    ]
    service = AsyncMock(spec=LiteratureResultService)
    service.get_papers.return_value = papers
    application = create_app()
    application.dependency_overrides[get_literature_result_service] = (
        lambda: service
    )

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/api/literature/runs/8/papers")

    response = asyncio.run(send_request())

    assert response.status_code == 200
    assert response.json()[0]["id"] == 20
    assert response.json()[0]["doi"] == "10.1000/example"
    assert response.json()[0]["position"] == 0
    assert response.json()[0]["relevance_score"] == 0.95
    assert response.json()[0]["relevance_reason"] == (
        "Directly addresses the requested problem"
    )
    assert response.json()[0]["matched_terms"] == ["oversmoothing"]
    service.get_papers.assert_awaited_once_with(8)


def test_literature_run_papers_maps_missing_run_to_404() -> None:
    service = AsyncMock(spec=LiteratureResultService)
    service.get_papers.side_effect = LiteratureRunNotFoundError(99)
    application = create_app()
    application.dependency_overrides[get_literature_result_service] = (
        lambda: service
    )

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/api/literature/runs/99/papers")

    response = asyncio.run(send_request())

    assert response.status_code == 404
    assert response.json() == {"detail": "Run with id 99 not found"}


def test_literature_api_confirms_paper_selection() -> None:
    selected_at = datetime(2026, 9, 16, tzinfo=timezone.utc)
    selection = PaperSelection(
        run_id=8,
        selected_paper_ids=[20, 10],
        code_requirements="Use PyTorch",
        selected_at=selected_at,
    )
    coordinator = AsyncMock(spec=ModuleWorkflowCoordinator)
    coordinator.confirm_paper_selection.return_value = selection
    application = create_app()
    application.dependency_overrides[get_module_workflow_coordinator] = (
        lambda: coordinator
    )

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/literature/runs/8/selection",
                json={
                    "selected_paper_ids": [20, 10],
                    "code_requirements": "Use PyTorch",
                },
            )

    response = asyncio.run(send_request())

    assert response.status_code == 201
    assert response.json() == selection.model_dump(mode="json")
    request = coordinator.confirm_paper_selection.await_args.args[1]
    assert coordinator.confirm_paper_selection.await_args.args[0] == 8
    assert request.selected_paper_ids == [20, 10]
    assert request.code_requirements == "Use PyTorch"


def test_literature_api_rejects_empty_paper_selection() -> None:
    coordinator = AsyncMock(spec=ModuleWorkflowCoordinator)
    application = create_app()
    application.dependency_overrides[get_module_workflow_coordinator] = (
        lambda: coordinator
    )

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/literature/runs/8/selection",
                json={"selected_paper_ids": []},
            )

    response = asyncio.run(send_request())

    assert response.status_code == 422
    coordinator.confirm_paper_selection.assert_not_awaited()


def test_literature_api_maps_duplicate_selection_to_409() -> None:
    coordinator = AsyncMock(spec=ModuleWorkflowCoordinator)
    coordinator.confirm_paper_selection.side_effect = PaperSelectionAlreadyExistsError(8)
    application = create_app()
    application.dependency_overrides[get_module_workflow_coordinator] = (
        lambda: coordinator
    )

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/literature/runs/8/selection",
                json={"selected_paper_ids": [20]},
            )

    response = asyncio.run(send_request())

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Paper selection for run 8 already exists",
        "code": "paper_selection_already_exists",
    }


def test_literature_api_maps_foreign_papers_to_422() -> None:
    coordinator = AsyncMock(spec=ModuleWorkflowCoordinator)
    coordinator.confirm_paper_selection.side_effect = InvalidPaperSelectionError(
        8, [20, 30]
    )
    application = create_app()
    application.dependency_overrides[get_module_workflow_coordinator] = (
        lambda: coordinator
    )

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/literature/runs/8/selection",
                json={"selected_paper_ids": [20, 30]},
            )

    response = asyncio.run(send_request())

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Papers [20, 30] do not belong to literature run 8",
        "code": "invalid_paper_selection",
        "details": {
            "run_id": 8,
            "invalid_paper_ids": [20, 30],
        },
    }


def test_literature_api_starts_paper_selection() -> None:
    prompt = PaperSelectionInterrupt(literature_run_id=8)
    coordinator = AsyncMock(spec=ModuleWorkflowCoordinator)
    coordinator.start_paper_selection.return_value = prompt
    application = create_app()
    application.dependency_overrides[get_module_workflow_coordinator] = (
        lambda: coordinator
    )

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/literature/runs/8/selection/start",
                json={"code_requirements": "Use PyTorch"},
            )

    response = asyncio.run(send_request())

    assert response.status_code == 200
    assert response.json() == prompt.model_dump(mode="json")
    coordinator.start_paper_selection.assert_awaited_once_with(
        run_id=8,
        code_requirements="Use PyTorch",
    )


def test_literature_api_starts_selection_without_code_requirements() -> None:
    prompt = PaperSelectionInterrupt(literature_run_id=8)
    coordinator = AsyncMock(spec=ModuleWorkflowCoordinator)
    coordinator.start_paper_selection.return_value = prompt
    application = create_app()
    application.dependency_overrides[get_module_workflow_coordinator] = (
        lambda: coordinator
    )

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/literature/runs/8/selection/start",
                json={},
            )

    response = asyncio.run(send_request())

    assert response.status_code == 200
    coordinator.start_paper_selection.assert_awaited_once_with(
        run_id=8,
        code_requirements=None,
    )


def test_literature_api_maps_progressed_workflow_to_409() -> None:
    coordinator = AsyncMock(spec=ModuleWorkflowCoordinator)
    coordinator.start_paper_selection.side_effect = WorkflowAlreadyProgressedError(8)
    application = create_app()
    application.dependency_overrides[get_module_workflow_coordinator] = (
        lambda: coordinator
    )

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/literature/runs/8/selection/start",
                json={},
            )

    response = asyncio.run(send_request())

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Workflow for literature run 8 has already progressed",
        "code": "workflow_already_progressed",
    }


def test_literature_api_starts_module_workflow() -> None:
    prompt = LiteratureWaitInterrupt(literature_run_id=8)
    coordinator = AsyncMock(spec=ModuleWorkflowCoordinator)
    coordinator.start_literature_workflow.return_value = prompt
    application = create_app()
    application.dependency_overrides[get_module_workflow_coordinator] = (
        lambda: coordinator
    )

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/literature/runs/8/workflow/start",
                json={"code_requirements": "Use PyTorch"},
            )

    response = asyncio.run(send_request())

    assert response.status_code == 200
    assert response.json() == prompt.model_dump(mode="json")
    coordinator.start_literature_workflow.assert_awaited_once_with(
        run_id=8,
        code_requirements="Use PyTorch",
    )


def test_literature_api_resumes_module_workflow_after_literature() -> None:
    prompt = PaperSelectionInterrupt(literature_run_id=8)
    coordinator = AsyncMock(spec=ModuleWorkflowCoordinator)
    coordinator.resume_after_literature_completion.return_value = prompt
    application = create_app()
    application.dependency_overrides[get_module_workflow_coordinator] = (
        lambda: coordinator
    )

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/literature/runs/8/workflow/literature/resume"
            )

    response = asyncio.run(send_request())

    assert response.status_code == 200
    assert response.json() == prompt.model_dump(mode="json")
    coordinator.resume_after_literature_completion.assert_awaited_once_with(8)


def test_literature_api_rejects_resume_before_literature_completion() -> None:
    coordinator = AsyncMock(spec=ModuleWorkflowCoordinator)
    coordinator.resume_after_literature_completion.side_effect = (
        LiteratureRunStateError(8, "resume literature workflow")
    )
    application = create_app()
    application.dependency_overrides[get_module_workflow_coordinator] = (
        lambda: coordinator
    )

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/literature/runs/8/workflow/literature/resume"
            )

    response = asyncio.run(send_request())

    assert response.status_code == 409
    assert response.json() == {
        "detail": (
            "Run with id 8 is not in a valid state to "
            "resume literature workflow"
        )
    }
