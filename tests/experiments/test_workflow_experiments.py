"""Synthetic contracts only: no network, Docker or training in unit tests."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI
import httpx
import pytest
from pydantic import ValidationError

from module_agent.api.exception_handlers import register_exception_handlers
from module_agent.experiments.api import experiment_router, get_experiment_service
from module_agent.experiments.domain import ExperimentBudget
from module_agent.experiments.jobs import PilotApproval, PilotJob, PilotProposal, PilotRequest
from module_agent.experiments import recipe
from module_agent.literature.adapters.database.models.paper import PaperModel
from module_agent.shared.exceptions import AppException
from module_agent.workflow.experiments import supports_paper


def proposal() -> PilotProposal:
    return PilotProposal(literature_run_id=7, paper_id=9, worker_id=uuid4(),
                         budget=ExperimentBudget(gpu_uuid="GPU-synthetic"))


@pytest.mark.parametrize("field,value", [("execute_code", False), ("allow_preparation_network", False),
    ("acknowledge_source_license", False), ("acknowledge_gpu_not_memory_capped", False)])
def test_every_approval_is_explicit(field, value):
    data = dict(proposal_sha256=proposal().digest(), execute_code=True, allow_preparation_network=True,
                acknowledge_source_license=True, acknowledge_gpu_not_memory_capped=True)
    data[field] = value
    with pytest.raises(ValidationError):
        PilotApproval.model_validate(data)


def test_web_cannot_supply_commands_urls_or_local_paths():
    p = proposal()
    request = dict(paper_id=9, worker_id=p.worker_id, budget=p.budget.model_dump())
    for field in ("command", "repository_url", "image", "repository_path"):
        with pytest.raises(ValidationError):
            PilotRequest.model_validate({**request, field: "untrusted"})


def test_budget_is_bound_to_frozen_proposal():
    p = proposal()
    changed = p.model_copy(update={"budget": p.budget.model_copy(update={"memory_mb": 8192})})
    assert p.digest() != changed.digest()
    assert p.digest() == PilotProposal.model_validate_json(p.model_dump_json()).digest()
    assert not recipe.verify_curated_sources({})
    assert all(len(digest) == 64 for digest in recipe.SOURCES.values())


@pytest.mark.parametrize("title,url,expected", [
    (recipe.TITLE, None, True), ("Anything", "https://arxiv.org/abs/2008.10400v2", True),
    ("A different MNIST paper", "https://arxiv.org/abs/2008.104001", False),
    ("P-3.12 Lightweight CNN", None, False), ("DropEdge", None, False),
    ("Wrong", "https://evil.example/abs/2008.10400", False),
])
def test_only_exact_paper_is_supported(title, url, expected):
    assert supports_paper(PaperModel(title=title, landing_page_url=url)) is expected


def test_public_endpoints_do_not_execute_and_download_is_authenticated_api_data():
    async def check():
        p = proposal()
        now = datetime.now(timezone.utc)
        job = PilotJob(id=p.id, literature_run_id=7, paper_id=9, status="draft", stage="awaiting_approval",
                       proposal=p, proposal_sha256=p.digest(), created_at=now, updated_at=now)
        service = AsyncMock()
        service.propose.return_value = job
        service.confirm.return_value = job.model_copy(update={"status": "queued"})
        service.cancel.return_value = job.model_copy(update={"status": "cancelled"})
        service.overview.return_value = {"jobs": [job.model_dump(mode="json")], "workers": [], "eligible_papers": []}
        service.artifact.side_effect = AppException("不存在", "missing", 404)
        app = FastAPI()
        app.include_router(experiment_router, prefix="/api")
        register_exception_handlers(app)
        app.dependency_overrides[get_experiment_service] = lambda: service
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            request = dict(paper_id=9, worker_id=str(p.worker_id), budget=p.budget.model_dump())
            assert (await client.post("/api/workflow/runs/7/experiments", json=request)).status_code == 201
            assert (await client.get("/api/workflow/runs/7/experiments")).status_code == 200
            path = f"/api/experiments/{p.id}"
            assert (await client.post(path + "/confirm", json={})).status_code == 422
            service.confirm.assert_not_awaited()
            approval = dict(proposal_sha256=p.digest(), execute_code=True, allow_preparation_network=True,
                            acknowledge_source_license=True, acknowledge_gpu_not_memory_capped=True)
            assert (await client.post(path + "/confirm", json=approval)).json()["status"] == "queued"
            assert (await client.post(path + "/cancel")).json()["status"] == "cancelled"
            assert (await client.get(path + "/artifacts/weights.pth")).status_code == 404
            assert (await client.get(path + "/artifacts/not%20allowed")).status_code == 422
    asyncio.run(check())


def test_cached_source_bytes_match_reviewed_archive_if_present():
    # Optional local check is not a prerequisite for a clean checkout.
    from module_agent.experiments.workspace import code_files

    path = Path("workspaces/reproduction/mnist-m5/pilot-20261107/source")
    if not path.exists():
        pytest.skip("local pilot evidence not present")
    assert recipe.verify_curated_sources(code_files(path))


def test_preparation_rejects_cache_symlinks(tmp_path):
    from module_agent.experiments.preparation import safe_target

    (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        safe_target(tmp_path, tmp_path / "link" / "file")
    with pytest.raises(ValueError):
        safe_target(tmp_path, tmp_path.parent / "outside")


def test_download_must_match_fixed_digest(tmp_path, monkeypatch):
    import hashlib
    from module_agent.experiments import preparation

    async def fake_command(*args):
        target = Path(args[args.index("--output") + 1])
        target.write_bytes(b"untrusted source")
        return ""

    monkeypatch.setattr(preparation, "command", fake_command)
    target = tmp_path / "file"
    with pytest.raises(ValueError, match="SHA256"):
        asyncio.run(preparation.download("https://example.invalid/test", target, "0" * 64))
    assert not target.exists()
    data = asyncio.run(preparation.download("https://example.invalid/test", target, hashlib.sha256(b"untrusted source").hexdigest()))
    assert data == b"untrusted source" and target.read_bytes() == data
