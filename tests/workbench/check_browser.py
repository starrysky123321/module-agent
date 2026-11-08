"""Optional browser contract checks using synthetic API responses.

Run: uv run --with playwright python tests/workbench/check_browser.py
This starts a temporary local UI server without database, LLM or Docker access.
It verifies interface behavior, not real paper reproduction or retrieval quality.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import socket
import tempfile
import threading
import time

from fastapi import FastAPI
from playwright.sync_api import expect, sync_playwright
import uvicorn

from module_agent.api.workbench import register_workbench
from module_agent.code.domain.artifact import CodeArtifact
from module_agent.literature.domain.recommendation import (
    LiteraturePaperRecommendation,
)
from module_agent.literature.domain.run import LiteratureRun
from module_agent.validation.domain.report import ValidationReport
from module_agent.workflow.result import ModuleBuildResult
from module_agent.shared.resources import ResourceSnapshot
from module_agent.experiments.jobs import PilotProposal


def main() -> None:
    screenshot_dir = Path(tempfile.mkdtemp(prefix="module-agent-workbench-"))
    app = FastAPI()
    register_workbench(app, api_prefix="/api")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "Temporary UI server did not start"

    requests: list[tuple[str, str, object]] = []
    errors: list[str] = []
    test_state = {"phase": "new", "starts": 0, "selections": 0, "admissions": 0, "offline": False, "health_failed": False, "resource_failed": False, "deleted": False, "deletes": 0, "plan_result": False}
    run: dict = {}
    saved_policy: dict = {}
    resources = ResourceSnapshot(
        scope="host", logical_cpu_count=8, available_cpu_count=4,
        memory_total_mb=8192, memory_available_mb=6144,
        workspace_total_mb=32768, workspace_free_mb=16384,
        gpu_status="unavailable", sandbox_ready=False,
        sandbox_reason="Synthetic contract fixture: sandbox is not configured.",
    ).model_dump(mode="json")
    now = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    workflow = {
        "literature_run_id": 7,
        "trace_id": "1e17bc49-ddd3-42ad-b930-8db30b72c330",
        "status": "waiting_for_literature",
        "deadline_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "created_at": now,
        "updated_at": now,
    }
    paper = LiteraturePaperRecommendation.model_validate({
        "id": 9, "source": "openalex", "source_id": "test-W9",
        "title": 'Synthetic contract test <img src=x onerror="window.injected=true">',
        "authors": ["Test Author"], "publication_year": 2025,
        "position": 0, "relevance_score": 0.82,
        "relevance_reason": "Synthetic fixture for UI testing only.",
        "landing_page_url": "javascript:window.injected=true",
        "doi": "10.0000/synthetic-test", "abstract": "Synthetic test abstract.",
    }).model_dump(mode="json")

    footprint_warning = "The exact configuration to achieve exactly 1,326 parameters and 920 FLOPs is not specified. The implemented architecture results in ~2,066 parameters."
    scaffold_warning = "Generated files are an unverified reproduction scaffold, not a completed implementation of the paper"
    planned_artifact = CodeArtifact.model_validate({
        "paper_id": 9, "origin": "reproduction_plan", "status": "reproduction_planned",
        "implementation_generated": True,
        "reproduction_plan": {
            "research_problem": "Designing and deploying a resource-efficient Convolutional Neural Network for handwritten digit recognition on microcontrollers and logic gate hardware.",
            "implementation_steps": ["Environment setup and data preparation", "Architecture design and quantization", "Evaluation and deployment profiling"],
            "inputs": ["MNIST dataset (28x28 grayscale images of handwritten digits)"],
            "outputs": ["Predicted digit class (0-9) for each input image"],
            "open_questions": ["What is the specific bit-width used for the integer weight quantization?"],
            "warnings": [footprint_warning],
        },
        "warnings": [footprint_warning, scaffold_warning],
    })
    planned_report = ValidationReport.model_validate({
        "literature_run_id": 7, "paper_id": 9, "artifact_origin": "reproduction_plan",
        "artifact_status": "reproduction_planned", "mode": "static", "status": "partial", "code_executed": False,
        "checks": [{"kind": "reproduction_plan", "status": "warning", "summary": "Reproduction plan requires clarification"}],
        "warnings": [footprint_warning, footprint_warning, scaffold_warning],
    })
    artifact = CodeArtifact.model_validate({
        "paper_id": 9, "origin": "official", "status": "repository_ready",
        "repository_url": "https://github.com/example/synthetic-test",
        "commit_sha": "a" * 40, "local_path": "/synthetic-workspace/test",
        "confidence": 0.9, "code_availability": "source_available",
    })
    report = ValidationReport.model_validate({
        "literature_run_id": 7, "paper_id": 9, "artifact_origin": "official",
        "artifact_status": "repository_ready", "mode": "static",
        "status": "passed", "code_executed": False,
        "checks": [{"kind": "syntax", "status": "passed", "summary": "Synthetic static check."}],
    })
    result = ModuleBuildResult.model_validate({
        "literature_run_id": 7, "status": "completed", "selected_paper_ids": [9],
        "selected_papers": [{"paper_id": 9, "source": "openalex", "source_id": "test-W9", "title": paper["title"]}],
        "code_artifacts": [artifact], "validation_reports": [report],
    }).model_dump(mode="json")
    pilot_jobs = []
    worker_id = "42b8b580-5113-42bf-81aa-5edb6dc56758"

    def api_route(route) -> None:
        request = route.request
        path = request.url.split("/api", 1)[1]
        body = request.post_data_json if request.post_data else None
        requests.append((request.method, path, body))

        def respond(payload: object, status: int = 200) -> None:
            route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

        if path == "/health/ready":
            respond({"detail": "Service unavailable"} if test_state["health_failed"] else {"status": "ready"}, 503 if test_state["health_failed"] else 200)
        elif request.headers.get("authorization") != "Bearer browser-contract-token":
            respond({"detail": "Valid bearer authentication is required"}, 401)
        elif path == "/system/resources":
            respond({"detail": "Resource probe unavailable"} if test_state["resource_failed"] else resources, 503 if test_state["resource_failed"] else 200)
        elif path == "/workflow/runs/7/experiments":
            if request.method == "POST":
                proposal = PilotProposal(literature_run_id=7, **body)
                pilot_jobs.append({"id": str(proposal.id), "status": "draft", "stage": "awaiting_approval",
                    "proposal": proposal.model_dump(mode="json"), "proposal_sha256": proposal.digest(), "created_at": now,
                    "log_tail": "", "artifacts": []})
                respond(pilot_jobs[-1], 201)
            else:
                respond({"notice": "Synthetic UI fixture only; no real experiment is performed.", "jobs": pilot_jobs,
                    "eligible_papers": [{"id": 9, "title": "Synthetic eligible M5 paper"}],
                    "workers": [{"id": worker_id, "resources": {**resources, "sandbox_ready": True,
                        "gpus": [{"uuid": "GPU-synthetic", "name": "Synthetic GPU", "memory_free_mb": 4096}]}}]})
        elif path.startswith("/experiments/"):
            job = pilot_jobs[-1]
            if path.endswith("/confirm"):
                assert body["proposal_sha256"] == job["proposal_sha256"]
                assert all(body[name] is True for name in ("execute_code", "allow_preparation_network", "acknowledge_source_license", "acknowledge_gpu_not_memory_capped"))
                job.update(status="running", stage="train", log_tail="Synthetic log <img src=x onerror=window.injected=true>")
                respond(job)
            elif path.endswith("/cancel"):
                job.update(status="cancelled", stage="cancelled")
                respond(job)
            elif "/artifacts/" in path:
                route.fulfill(status=200, body="synthetic download, not actual weights")
        elif path == "/literature/runs/7" and request.method == "DELETE":
            test_state["deletes"] += 1
            if test_state["phase"] == "code":
                respond({"detail": "任务仍在执行，暂不能删除。"}, 409)
            elif test_state["deletes"] == 1:
                respond({"detail": "Synthetic deletion unavailable"}, 503)
            else:
                test_state["deleted"] = True
                route.fulfill(status=204, body="")
        elif test_state["deleted"] and (path.startswith("/literature/runs/7") or path.startswith("/workflow/runs/7")):
            respond({"detail": "Task not found"}, 404)
        elif path == "/system/resources/validate":
            assert body["workspace_limit_mb"] == 768
            test_state["admissions"] += 1
            if test_state["admissions"] == 1:
                respond({"detail": "Synthetic budget admission rejected"}, 422)
            else:
                respond(resources)
        elif path == "/literature/runs" and request.method == "POST":
            run.update(LiteratureRun.model_validate({"id": 7, "request": body, "created_at": now}).model_dump(mode="json"))
            respond(run, 201)
        elif path == "/literature/runs/7":
            if test_state["offline"]:
                respond({"detail": "Synthetic service unavailable"}, 503)
            else:
                respond({**run, "status": "completed" if test_state["phase"] in {"papers", "code", "validation", "done", "failed", "cancelled", "timed_out"} else "queued" if test_state["phase"] == "queued" else "running" if test_state["phase"] == "search" else "pending"})
        elif path == "/literature/runs/7/workflow/start":
            assert body["validation_policy"]["mode"] == "static"
            assert body["validation_policy"]["cpu_limit"] == 1.5
            assert body["validation_policy"]["workspace_limit_mb"] == 768
            test_state["starts"] += 1
            if test_state["starts"] == 1:
                respond({"detail": "Synthetic start failure; recover using saved ID"}, 503)
            else:
                saved_policy.update(body["validation_policy"])
                test_state["phase"] = "queued"
                respond({"literature_run_id": 7, "message": "waiting"})
        elif path == "/workflow/runs/7":
            if test_state["phase"] == "new":
                respond({"detail": "Workflow not started"}, 404)
            else:
                status = {"queued": "waiting_for_literature", "search": "waiting_for_literature", "papers": "waiting_for_selection", "code": "waiting_for_code", "validation": "running", "done": "completed", "failed": "failed", "cancelled": "cancelled", "timed_out": "timed_out"}[test_state["phase"]]
                respond({**workflow, "status": status, **({"finished_at": datetime.now(timezone.utc).isoformat()} if status in {"completed", "failed", "cancelled", "timed_out"} else {})})
        elif path == "/workflow/runs/7/nodes":
            nodes = [{
                "node": "literature_dispatch", "attempt": 1, "status": "completed",
                "duration_ms": 170, "input_summary": {}, "output_summary": {}, "created_at": now,
            }]
            if test_state["phase"] in {"validation", "done"}:
                nodes.append({**nodes[0], "node": "code_wait"})
            respond(nodes)
        elif path == "/workflow/runs/7/resources":
            respond(saved_policy)
        elif path == "/literature/runs/7/papers":
            respond([paper])
        elif path == "/literature/runs/7/selection":
            assert body["selected_paper_ids"] == [9]
            test_state["selections"] += 1
            if test_state["selections"] == 1:
                respond({"detail": "Synthetic selection failure"}, 503)
            else:
                test_state["phase"] = "code"
                respond({"literature_run_id": 7, "selected_paper_ids": [9]}, 201)
        elif path == "/workflow/runs/7/result":
            payload = {**result, "code_artifacts": [planned_artifact.model_dump(mode="json")], "validation_reports": [planned_report.model_dump(mode="json")]} if test_state["plan_result"] else result
            respond(payload if test_state["phase"] == "done" else {"detail": "No final result"}, 200 if test_state["phase"] == "done" else 409)
        else:
            respond({"detail": "Not found"}, 404)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1100}, accept_downloads=True, locale="zh-CN")
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/api/**", api_route)
            page.goto(f"http://127.0.0.1:{port}/")
            expect(page.locator("#health")).to_contain_text("服务已就绪")
            expect(page.locator("#search-options")).not_to_have_attribute("open", "")
            expect(page.locator("#resource-options")).not_to_have_attribute("open", "")
            expect(page.locator("#resource-feedback")).to_have_attribute("data-state", "error")
            expect(page.locator("#create-button")).to_be_enabled()
            expect(page.get_by_role("button", name="连接设置", exact=True)).to_have_count(1)
            expect(page.locator(".sidebar-empty")).to_have_text("暂无记录")
            expect(page.locator("#clear-history")).to_be_hidden()
            assert page.locator(".sidebar").bounding_box()["width"] == 240
            assert page.locator("main").bounding_box()["width"] <= 1100
            assert page.locator(".guide-card, .guide-art, .workflow-strip").count() == 0
            expect(page.locator("#style-alert")).to_be_hidden()
            for width in (1440, 1920):
                page.set_viewport_size({"width": width, "height": 1100})
                metrics = page.evaluate("""() => ({
                    icons: [...document.querySelectorAll('.nav-icon')].map(el => ({width:el.getBoundingClientRect().width, height:el.getBoundingClientRect().height})),
                    labels: [...document.querySelectorAll('.nav-label')].map(el => ({height:el.getBoundingClientRect().height, whiteSpace:getComputedStyle(el).whiteSpace, clipped:el.scrollWidth > el.clientWidth})),
                    tags: [...document.querySelectorAll('.topic-example')].map(el => ({left:el.getBoundingClientRect().left, right:el.getBoundingClientRect().right, top:el.getBoundingClientRect().top})),
                    formBorder: getComputedStyle(document.querySelector('#topic')).borderTopStyle,
                    font: getComputedStyle(document.querySelector('#topic')).fontFamily,
                    width: document.querySelector('main').getBoundingClientRect().width,
                })""")
                assert all(icon["width"] == icon["height"] == 18 for icon in metrics["icons"]), metrics
                assert all(label["height"] <= 21 and label["whiteSpace"] == "nowrap" and not label["clipped"] for label in metrics["labels"]), metrics
                assert all(right["left"] - left["right"] >= 8 and left["top"] == right["top"] for left, right in zip(metrics["tags"], metrics["tags"][1:], strict=False)), metrics
                assert metrics["width"] <= 1100 and metrics["formBorder"] == "solid" and "sans-serif" in metrics["font"], metrics
                page.screenshot(path=str(screenshot_dir / f"workbench-{width}.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

            page.set_viewport_size({"width": 390, "height": 844})
            expect(page.locator("#open-run-mobile")).to_be_visible()
            expect(page.locator(".sidebar")).not_to_be_visible()
            expect(page.locator("#connection-settings")).not_to_be_visible()
            page.locator("#menu-toggle").click()
            expect(page.locator("#connection-settings")).to_be_visible()
            page.keyboard.press("Escape")
            expect(page.locator("#menu-toggle")).to_be_focused()
            expect(page.locator(".sidebar")).not_to_be_visible()
            assert page.locator("#start-date").bounding_box()["width"] > 200
            page.screenshot(path=str(screenshot_dir / "workbench-mobile.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.set_viewport_size({"width": 1440, "height": 1100})

            page.locator("#connection-settings").click()
            page.locator("#api-token").fill("browser-contract-token")
            page.locator("#settings-form button[type=submit]").click()
            expect(page.locator("#resource-feedback")).to_have_attribute("data-state", "success")
            test_state["health_failed"] = True
            page.locator("#connection-settings").click()
            page.locator("#api-token").fill("browser-contract-token")
            page.locator("#settings-form button[type=submit]").click()
            expect(page.locator("#health")).to_have_attribute("data-state", "error")
            expect(page.locator("#retry-connection")).to_be_visible()
            test_state["health_failed"] = False
            page.locator("#retry-connection").click()
            expect(page.locator("#health")).to_have_attribute("data-state", "success")
            test_state["resource_failed"] = True
            page.locator("#detect-resources").evaluate("el => el.click()")
            expect(page.locator("#resource-feedback")).to_have_attribute("data-state", "error")
            expect(page.locator("#create-button")).to_be_enabled()
            test_state["resource_failed"] = False
            page.locator("#retry-resources").click()
            expect(page.locator("#resource-feedback")).to_have_attribute("data-state", "success")
            page.locator("#topic").fill("   ")
            page.locator("#create-button").click()
            expect(page.locator("#topic-error")).to_be_visible()
            page.locator("[data-topic]").first.click()
            expect(page.locator("#topic-error")).to_be_hidden()
            page.locator("#start-date").fill("2026-12-01")
            page.locator("#end-date").fill("2026-01-01")
            page.locator("#create-button").click()
            expect(page.locator("#date-error")).to_contain_text("开始日期不能晚于结束日期")
            assert not any(method == "POST" for method, _, _ in requests)
            page.locator("#start-date").fill("2023-01-01")
            page.locator("#end-date").fill("2026-01-01")
            try:
                expect(page.locator("#create-button")).to_be_enabled()
            except AssertionError:
                print("Resource discovery diagnostic:", page.locator("#resource-message").inner_text(), errors, requests)
                raise
            page.locator("#resource-options > summary").click()
            expect(page.locator("#resource-summary")).to_contain_text("4 核")
            page.locator("#cpu-limit").fill("1.5")
            page.locator("#memory-limit").fill("512")
            page.locator("#workspace-limit").fill("768")
            page.locator("#temporary-storage").fill("128")
            page.locator("#topic").fill("Synthetic browser test")
            page.locator("#search-options > summary").click()
            page.locator("#keywords").fill("test, attention")
            page.locator("#create-button").click()
            expect(page.locator("#notice")).to_contain_text("Synthetic budget admission rejected")
            assert not any(method == "POST" and path == "/literature/runs" for method, path, _ in requests)
            page.locator("#create-button").click()
            expect(page.locator("#notice")).to_contain_text("Synthetic start failure")
            expect(page.locator('[data-action="start"]')).to_be_visible()
            assert page.url.endswith("#run=7")
            page.locator('[data-action="start"]').click()
            expect(page.locator("#progress-title")).to_have_text("等待文献检索")
            expect(page.locator("#run-progress")).to_have_attribute("data-mode", "queued")
            test_state["phase"] = "search"
            page.locator("#refresh-run").click()
            expect(page.locator("#progress-title")).to_have_text("正在检索文献")
            expect(page.locator("#run-progress")).to_have_attribute("data-mode", "working")
            assert page.locator("#run-progress").get_attribute("aria-valuenow") is None
            assert page.locator(".progress-fill").evaluate("el => getComputedStyle(el).animationName") == "waiting"
            elapsed = page.locator("#progress-elapsed").inner_text()
            expect(page.locator("#progress-elapsed")).not_to_have_text(elapsed, timeout=2500)
            page.screenshot(path=str(screenshot_dir / "workbench-literature-wait.png"), full_page=True)
            expect(page.locator("#run-resources")).to_contain_text("CPU ≤ 1.5 核")
            assert sum(method == "POST" and path == "/literature/runs" for method, path, _ in requests) == 1

            test_state["phase"] = "papers"
            page.locator("#refresh-run").click()
            checkbox = page.locator('[data-paper="9"]')
            expect(checkbox).to_be_visible()
            expect(page.locator("#papers-list")).to_contain_text("撤稿状态未核验")
            paper["integrity"] = {"status":"retracted", "sources":["crossref"], "warnings":[]}
            page.locator("#refresh-run").click()
            expect(checkbox).to_be_disabled()
            expect(page.locator("#confirm-selection")).to_be_disabled()
            page.screenshot(path=str(screenshot_dir / "workbench-retracted-disabled.png"), full_page=True)
            paper["integrity"] = {"status":"not_flagged", "sources":["openalex"], "warnings":["Crossref 未能核验，不能据此认定无撤稿"]}
            page.locator("#refresh-run").click()
            expect(checkbox).to_be_enabled()
            expect(page.locator("#papers-list")).to_contain_text("核验不完整")
            page.locator("#papers-list summary").filter(has_text="元数据核验说明").click()
            expect(page.locator("#papers-list")).to_contain_text("不能据此认定无撤稿")
            expect(page.locator("#progress-title")).to_have_text("请选择论文")
            expect(page.locator("#run-progress")).to_have_attribute("data-mode", "waiting")
            expect(page.locator("#run-progress")).to_have_attribute("aria-valuenow", "1")
            assert page.locator(".progress-fill").evaluate("el => getComputedStyle(el).animationName") == "none"
            checkbox.check()
            page.locator("#selection-requirements").fill("Synthetic code requirements")
            page.locator("#confirm-selection").click()
            expect(page.locator("#notice")).to_contain_text("Synthetic selection failure")
            expect(checkbox).to_be_checked()
            expect(page.locator("#selection-requirements")).to_have_value("Synthetic code requirements")
            page.locator("#confirm-selection").click()
            expect(page.locator("#progress-title")).to_have_text("正在处理代码")
            expect(page.locator("#run-progress")).to_have_attribute("data-mode", "working")
            page.screenshot(path=str(screenshot_dir / "workbench-code-wait.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(screenshot_dir / "workbench-code-mobile.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1100})
            test_state["offline"] = True
            page.locator("#refresh-run").click()
            expect(page.locator("#run-progress")).to_have_attribute("data-mode", "unavailable")
            assert page.locator(".progress-fill").evaluate("el => getComputedStyle(el).animationName") == "none"
            test_state["offline"] = False
            test_state["phase"] = "validation"
            page.locator("#refresh-run").click()
            expect(page.locator("#progress-title")).to_have_text("正在验证代码")

            test_state["phase"] = "done"
            page.locator("#refresh-run").click()
            expect(page.locator("#results-panel")).to_be_visible()
            panel = page.locator("#experiments-panel")
            expect(panel).to_be_visible()
            panel.get_by_role("button", name="生成计划，不执行代码", exact=True).click()
            confirm = panel.get_by_role("button", name="确认预算并开始试跑", exact=True)
            expect(confirm).to_be_visible()
            before = len([r for r in requests if r[1].endswith("/confirm")])
            confirm.click()
            expect(page.locator("#notice")).to_contain_text("逐项确认")
            assert len([r for r in requests if r[1].endswith("/confirm")]) == before
            for item in panel.locator("input[type=checkbox]").all():
                item.check()
            confirm.click()
            expect(panel).to_contain_text("训练 M5")
            panel.locator("details[data-experiment-key^=logs] > summary").click()
            expect(panel.locator(".experiment-log")).to_be_visible()
            assert panel.locator("img").count() == 0
            panel.get_by_role("button", name="检测执行机", exact=True).click()
            expect(panel.locator(".experiment-log")).to_be_visible()
            panel.get_by_role("button", name="停止实验", exact=True).click()
            expect(panel).to_contain_text("已停止")
            pilot_jobs[-1].update(status="completed", stage="finished", artifacts=["metrics.json"],
                result={"metrics": {"accuracy_percent": 90, "correct": 9000, "wrong": 1000, "evaluated_samples": 10000, "completed_epochs": 2}})
            panel.get_by_role("button", name="检测执行机", exact=True).click()
            expect(panel).to_contain_text("90.00%")
            expect(panel).to_contain_text("不可与论文指标直接比较")
            with page.expect_download():
                panel.get_by_role("button", name="下载 指标", exact=True).click()
            for width in (1440, 1920, 390):
                page.set_viewport_size({"width": width, "height": 1100})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                panel.screenshot(path=str(screenshot_dir / f"synthetic-experiment-{width}.png"))
            page.set_viewport_size({"width": 1440, "height": 1100})
            expect(page.locator("#run-progress")).to_have_attribute("data-mode", "complete")
            expect(page.locator("#run-progress")).to_have_attribute("aria-valuenow", "4")
            expect(page.locator(".report-boundary")).to_contain_text("没有执行论文代码")
            expect(page.locator(".report-boundary")).to_contain_text("尚未验证论文指标")
            evidence_button = page.get_by_text("代码来源与证据", exact=True)
            expect(evidence_button).to_have_css("border-top-style", "solid")
            expect(evidence_button).to_have_css("cursor", "pointer")
            expect(evidence_button).to_have_css("min-height", "36px")
            evidence_button.click()
            expect(page.locator(".evidence-matrix")).to_be_visible()
            expect(evidence_button.locator("..")).to_have_attribute("open", "")
            evidence_button.press("Enter")
            expect(page.locator(".evidence-matrix")).to_be_hidden()
            page.get_by_text("检查明细", exact=True).click()
            expect(page.locator(".checks")).to_be_visible()
            page.screenshot(path=str(screenshot_dir / "workbench-result.png"), full_page=True)
            assert page.locator('#papers-list img').count() == 0
            assert page.locator('a[href^="javascript:"]').count() == 0
            assert page.evaluate("window.injected !== true")
            with page.expect_download() as download_info:
                page.locator("#export-run").click()
            download = download_info.value
            record = json.loads(Path(download.path()).read_text())
            assert record["result"]["validation_reports"][0]["code_executed"] is False
            assert record["resource_policy"]["workspace_limit_mb"] == 768
            assert "browser-contract-token" not in page.evaluate("JSON.stringify(localStorage)")

            # Historical English plans get Chinese summaries, not raw JSON or
            # duplicated warning dumps. Originals remain available and exported.
            test_state["plan_result"] = True
            page.locator("#refresh-run").click()
            expect(page.locator("#results-list")).to_contain_text("待补充论文信息（未复现）")
            assert "部分通过" not in page.locator("#results-list").inner_text()
            assert footprint_warning not in page.locator("#results-list").inner_text()
            page.get_by_text("注意事项（2）", exact=True).click()
            expect(page.locator(".artifact-warnings .warning-item")).to_have_count(2)
            expect(page.locator(".artifact-warnings")).to_contain_text("1,326")
            expect(page.locator(".artifact-warnings")).to_contain_text("2,066")
            assert footprint_warning not in page.locator(".artifact-warnings").inner_text()
            page.get_by_text("复现计划与待确认问题", exact=True).click()
            expect(page.locator(".readable-details")).to_contain_text("并非逐句译文")
            expect(page.locator(".readable-details")).to_contain_text("需要确认整数权重量化采用的具体位宽")
            page.get_by_text("检查明细", exact=True).click()
            expect(page.locator(".checks")).to_contain_text("复现方案仍需补充信息和确认细节")
            expect(page.locator(".report-summary")).to_contain_text("方案检查：0 项通过，1 项提醒")
            for width in (1440, 1920):
                page.set_viewport_size({"width": width, "height": 1100})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.evaluate("window.scrollTo(0, 0)")
                page.screenshot(path=str(screenshot_dir / f"chinese-plan-{width}.png"), full_page=True, animations="disabled")
            with page.expect_download() as plan_download:
                page.locator("#export-run").click()
            exported = json.loads(Path(plan_download.value.path()).read_text())
            assert exported["result"]["code_artifacts"][0]["warnings"][0] == footprint_warning
            test_state["plan_result"] = False
            page.locator("#refresh-run").click()
            expect(page.get_by_text("代码来源与证据", exact=True)).to_be_visible()

            page.reload()
            expect(page.locator("#notice")).to_contain_text("API 需要认证")
            page.locator("#connection-settings").click()
            page.locator("#api-token").fill("browser-contract-token")
            page.locator("#settings-form button[type=submit]").click()
            expect(page.locator("#results-panel")).to_be_visible()
            expect(page.locator("#run-resources")).to_contain_text("CPU ≤ 1.5 核")
            expect(page.locator("#history-count")).to_have_text("1")
            assert sum(method == "POST" and path == "/literature/runs" for method, path, _ in requests) == 1
            resources.update({
                "sandbox_ready": True, "gpu_status": "detected",
                "gpus": [{"index": 0, "uuid": "GPU-contract-123", "name": "Synthetic GPU", "memory_total_mb": 8192, "memory_free_mb": 6144}],
            })
            page.locator("#new-task").click()
            if page.locator("#resource-options").get_attribute("open") is None:
                page.locator("#resource-options > summary").click()
            page.locator("#detect-resources").click()
            expect(page.locator("#gpu-summary")).to_contain_text("Synthetic GPU")
            page.locator("#execution-mode").select_option("sandbox")
            expect(page.locator("#gpu-device")).to_be_enabled()
            page.locator("#gpu-device").select_option("GPU-contract-123")
            page.locator("#mnist-example").click()
            expect(page.locator("#topic")).to_have_value("手写数字识别（MNIST）")
            page.screenshot(path=str(screenshot_dir / "workbench-resource-contract.png"), full_page=True)
            for status in ("failed", "cancelled", "timed_out"):
                test_state["phase"] = status
                page.locator("#open-run").click()
                page.locator("#run-id-input").fill("7")
                page.locator("#open-form button[type=submit]").click()
                expect(page.locator("#run-progress")).to_have_attribute("data-mode", status)
            # Confirmed removal must call the real DELETE contract. Failed or
            # active-task deletion leaves both the page and history intact.
            page.once("dialog", lambda dialog: dialog.dismiss())
            page.locator("#delete-run").click()
            assert test_state["deletes"] == 0
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator('[data-remove-history="7"]').click()
            expect(page.locator("#notice")).to_contain_text("Synthetic deletion unavailable")
            expect(page.locator("#history-count")).to_have_text("1")
            test_state["phase"] = "code"
            page.locator("#refresh-run").click()
            expect(page.locator("#progress-title")).to_have_text("正在处理代码")
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator("#delete-run").click()
            expect(page.locator("#notice")).to_contain_text("任务仍在执行")
            expect(page.locator("#history-count")).to_have_text("1")
            test_state["phase"] = "done"
            page.locator("#refresh-run").click()
            expect(page.locator("#results-panel")).to_be_visible()
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator("#clear-history").click()
            expect(page.locator("#notice")).to_contain_text("任务 #7 已删除")
            expect(page.locator("#create-view")).to_be_visible()
            expect(page.locator("#run-view")).to_be_hidden()
            expect(page.locator("#history-count")).to_have_text("0")
            assert "#run=" not in page.url
            assert json.loads(page.evaluate("localStorage.getItem('module-agent.workbench.history.v1')")) == []
            page.locator("#open-run").click()
            page.locator("#run-id-input").fill("7")
            page.locator("#open-form button[type=submit]").click()
            expect(page.locator("#notice")).to_contain_text("Task not found")
            expect(page.locator("#history-count")).to_have_text("0")
            # Batch deletion keeps failed/active items instead of blindly
            # clearing the list when only some requests succeeded.
            batch_context = browser.new_context(viewport={"width": 1440, "height": 1080})
            batch_context.add_init_script("localStorage.setItem('module-agent.workbench.history.v1', JSON.stringify([501,502,503].map(id => ({id, topic:'Batch fixture '+id, date:'2026-11-02'}))))")
            batch_calls = []

            def batch_api(route):
                path = route.request.url.split("/api", 1)[1]
                if route.request.method == "DELETE":
                    batch_calls.append(path)
                    if path.endswith("/502"):
                        route.fulfill(status=409, content_type="application/json", body='{"detail":"任务仍在执行"}')
                    else:
                        route.fulfill(status=204, body="")
                else:
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(resources if path == "/system/resources" else {"status": "ready"}))

            batch_page = batch_context.new_page()
            batch_page.on("pageerror", lambda error: errors.append(str(error)))
            batch_page.route("**/api/**", batch_api)
            batch_page.goto(f"http://127.0.0.1:{port}/")
            expect(batch_page.locator("#history-count")).to_have_text("3")
            batch_page.once("dialog", lambda dialog: dialog.accept())
            batch_page.locator("#clear-history").click()
            expect(batch_page.locator("#notice")).to_contain_text("已删除 2 个任务")
            expect(batch_page.locator("#notice")).to_contain_text("#502")
            expect(batch_page.locator("#history-count")).to_have_text("1")
            expect(batch_page.locator('[data-run="502"]')).to_be_visible()
            assert len(batch_calls) == 3
            batch_context.close()
            # Hold probes and submission to observe real pending UI states and
            # exercise the non-blocking static path without creating a real run.
            isolated = browser.new_context(viewport={"width": 1280, "height": 960}, locale="zh-CN")
            pending: dict = {}
            submissions: list = []

            def delayed_api(route) -> None:
                path = route.request.url.split("/api", 1)[1]
                if path in {"/health/ready", "/system/resources"}:
                    pending[path] = route
                elif path == "/literature/runs":
                    submissions.append(route)
                else:
                    raise AssertionError(f"Unexpected default-static request: {path}")

            pending_page = isolated.new_page()
            pending_page.on("pageerror", lambda error: errors.append(str(error)))
            pending_page.route("**/api/**", delayed_api)
            pending_page.goto(f"http://127.0.0.1:{port}/")
            expect(pending_page.locator("#resource-feedback")).to_have_attribute("data-state", "loading")
            expect(pending_page.locator("#health")).to_have_attribute("data-state", "loading")
            expect(pending_page.locator("#create-button")).to_be_enabled()
            for _ in range(100):
                if len(pending) == 2:
                    break
                pending_page.wait_for_timeout(20)
            for path in ("/health/ready", "/system/resources"):
                assert path in pending
                pending[path].fulfill(status=503, content_type="application/json", body='{"detail":"Temporarily unavailable"}')
            expect(pending_page.locator("#resource-feedback")).to_have_attribute("data-state", "error")
            expect(pending_page.locator("#create-button")).to_be_enabled()
            pending_page.locator("#topic").fill("Default static submission contract")
            pending_page.evaluate("const form = document.querySelector('#search-form'); form.requestSubmit(); form.requestSubmit();")
            expect(pending_page.locator("#create-button")).to_be_disabled()
            expect(pending_page.locator("#create-button")).to_have_attribute("aria-busy", "true")
            expect(pending_page.locator("#topic")).to_be_disabled()
            pending_page.wait_for_timeout(200)
            assert len(submissions) == 1
            submissions[0].fulfill(status=503, content_type="application/json", body='{"detail":"Synthetic submission failure"}')
            expect(pending_page.locator("#create-button")).to_be_enabled()
            expect(pending_page.locator("#topic")).to_have_value("Default static submission contract")
            expect(pending_page.locator("#notice")).to_contain_text("Synthetic submission failure")
            pending_page.locator("#resource-options > summary").click()
            pending_page.locator("#cpu-limit").fill("1.5")
            pending_page.locator("#create-button").click()
            expect(pending_page.locator("#notice")).to_contain_text("自定义资源预算或沙箱验证需要先成功检测")
            assert len(submissions) == 1
            isolated.close()

            # Missing styles must be explicit, and SVGs must remain bounded
            # even when the external stylesheet cannot be downloaded.
            unstyled = context.new_page()
            unstyled.on("pageerror", lambda error: errors.append(str(error)))
            unstyled.route("**/api/**", api_route)
            unstyled.route("**/ui/assets/**/*.css", lambda route: route.abort())
            unstyled.goto(f"http://127.0.0.1:{port}/")
            expect(unstyled.locator("#style-alert")).to_be_visible()
            assert all(icon["width"] == icon["height"] == 18 for icon in unstyled.locator(".nav-icon").evaluate_all("els => els.map(el => ({width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height}))"))
            unstyled.unroute("**/ui/assets/**/*.css")
            unstyled.locator("#retry-styles").click()
            expect(unstyled.locator("#style-alert")).to_be_hidden()
            expect(unstyled.locator("#topic")).to_have_css("border-top-style", "solid")
            unstyled.close()
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()

    print("Browser checks passed: compact layout, queued/search/code/validation progress, elapsed timer, offline/terminal states, selection, export and budget recovery.")
    print(f"Screenshots (empty workbench, no real task claims): {screenshot_dir}")


if __name__ == "__main__":
    main()
