import assert from "node:assert/strict";
import test from "node:test";
import {
  ApiError, WorkbenchApi, buildResourcePolicy, buildSearchRequest, evidenceSummary,
  escapeHtml, parseRunId, safeUrl,
  workflowProgress, elapsedTime, paperIntegrityDisplay, repositoryOriginNote,
} from "../../src/module_agent/api/workbench_assets/core.mjs";
import { chineseMessage, chineseWarnings, artifactOutcome, legacyPlanOutline, dependencyDisplay } from "../../src/module_agent/api/workbench_assets/locale-zh.mjs";
import { experimentSummary } from "../../src/module_agent/api/workbench_assets/experiments.mjs";

test("pilot summary uses measured counts, never a plan or copied accuracy", () => {
  assert.equal(experimentSummary({ status: "draft" }), "");
  assert.match(experimentSummary({ result: { metrics: { accuracy_percent: 97.25, correct: 9725, evaluated_samples: 10000, wrong: 275, completed_epochs: 2 } } }), /97.25%.*9725.*10000.*275/);
});

test("old official labels and repo self-claims do not imply verified authorship", () => {
  assert.match(repositoryOriginNote({origin:"official",evidence:[{evidence_type:"paper_url"}]}).label,/待复核/);
  assert.match(repositoryOriginNote({origin:"unknown",evidence:[{evidence_type:"implementation_claim"}]}).label,/待核验/);
  assert.equal(repositoryOriginNote({origin:"official",evidence:[{evidence_type:"implementation_url"},{evidence_type:"title"}]}),null);
});

test("integrity distinguishes unknown, incomplete and known retraction without claiming validity", () => {
  assert.equal(paperIntegrityDisplay({}).label, "撤稿状态未核验");
  assert.equal(paperIntegrityDisplay({ integrity:{status:"not_flagged",warnings:["Crossref timeout"]} }).label, "核验不完整");
  assert.equal(paperIntegrityDisplay({ integrity:{status:"retracted"} }).blocked, true);
  assert.equal(paperIntegrityDisplay({ integrity:{status:"notice"} }).blocked, true);
  assert.equal(paperIntegrityDisplay({ integrity:{status:"unknown"} }).blocked, false);
  assert.match(paperIntegrityDisplay({ integrity:{status:"not_flagged"} }).note, /不代表/);
});

test("known diagnostics are Chinese without rewriting their original", () => {
  const raw = "Reproduction plan requires clarification";
  assert.deepEqual(chineseMessage(raw), { text: "复现方案仍需补充信息和确认细节。", original: raw });
  assert.equal(chineseMessage("这是中文说明。").original, null);
  assert.equal(chineseMessage("Unknown historical warning").original, "Unknown historical warning");
  assert.match(chineseMessage("Unknown historical warning").text, /尚无中文译文/);
});

test("artifact/report duplicates are merged while distinct originals survive", () => {
  const groups = chineseWarnings(["Repository license could not be identified"], ["Repository  license could not be identified", "Different historical warning", "Another historical warning"]);
  assert.equal(groups.length, 2);
  assert.equal(groups[0].text, "未识别到仓库许可证。");
  assert.equal(groups[1].originals.length, 2);
});

test("parameter mismatch translations preserve the actual reported numbers", () => {
  const text = "The exact configuration to achieve exactly 1,326 parameters and 920 FLOPs is not specified. The implemented architecture results in ~2,066 parameters.";
  const translated = chineseMessage(text);
  assert.match(translated.text, /1,326/);
  assert.match(translated.text, /920 FLOPs/);
  assert.match(translated.text, /2,066/);
  assert.match(translated.text, /不能视为原论文实现/);
  assert.equal(translated.original, text);
});

test("a plan-only partial result is not presented as partial scientific reproduction", () => {
  const artifact = { status: "reproduction_planned", reproduction_plan: { open_questions: ["Missing architecture"] } };
  const before = JSON.stringify(artifact);
  assert.equal(artifactOutcome(artifact, { status: "partial" }).label, "待补充论文信息（未复现）");
  assert.equal(JSON.stringify(artifact), before);
  assert.equal(artifactOutcome({ status: "repository_ready" }, { status: "partial" }).label, "检查有提醒");
});

test("legacy outlines are labeled summaries, and do not fabricate a translation", () => {
  assert.match(legacyPlanOutline({ research_problem: "Unknown historical topic" })[0], /尚无可靠的中文步骤摘要/);
  const steps = legacyPlanOutline({ research_problem: "CNN architecture and quantization for a microcontroller", implementation_steps: ["Evaluation of accuracy"] });
  assert.ok(steps.some((text) => text.includes("量化")));
  assert.ok(steps.some((text) => text.includes("目前不代表已经执行")));
  assert.match(legacyPlanOutline({ research_problem: "Resource constrained method" })[0], /尚无可靠的中文步骤摘要/);
});

test("dependency display preserves identifiers and version constraints", () => {
  assert.equal(dependencyDisplay("torch-or>=1.0"), "torch-or>=1.0");
  assert.equal(dependencyDisplay("torch (>=2)"), "torch (>=2)");
  assert.equal(dependencyDisplay("PyTorch or TensorFlow (for model training)"), "PyTorch 或 TensorFlow");
});

const form = {
  topic: " Graph attention ", start_date: "2020-01-01", end_date: "2026-10-22",
  keywords: "GAT, node classification，GAT", max_results: "5",
};

const capacity = {
  available_cpu_count: 4, memory_available_mb: 4096, workspace_free_mb: 8192,
  sandbox_ready: true, gpus: [{ uuid: "GPU-test-123" }],
};
const budget = {
  cpu_limit: "1.5", memory_limit_mb: "1024", workspace_limit_mb: "2048",
  temporary_storage_mb: "256", timeout_seconds: "60", validation_mode: "static",
};

test("task deletion uses DELETE and accepts an empty 204 response", async () => {
  const calls = [];
  const api = new WorkbenchApi("/api", async (url, options) => {
    calls.push([url, options.method]);
    return new Response(null, { status: 204 });
  });
  assert.equal(await api.remove(9), null);
  assert.deepEqual(calls, [["/api/literature/runs/9", "DELETE"]]);
  assert.throws(() => api.remove("9/selection"));
});

test("resource choices produce numeric task budget and keep static as default", () => {
  const policy = buildResourcePolicy(budget, capacity);
  assert.equal(policy.cpu_limit, 1.5);
  assert.equal(policy.workspace_limit_mb, 2048);
  assert.equal(policy.mode, "static");
  assert.equal(policy.allow_network, false);
  assert.deepEqual(policy.gpu_device_ids, []);
});

test("resource choices reject impossible capacity and do not invent missing detection", () => {
  assert.throws(() => buildResourcePolicy(budget, null));
  assert.throws(() => buildResourcePolicy({ ...budget, cpu_limit: "5" }, capacity));
  assert.throws(() => buildResourcePolicy({ ...budget, memory_limit_mb: "8192" }, capacity));
  assert.throws(() => buildResourcePolicy({ ...budget, workspace_limit_mb: "16384" }, capacity));
  assert.throws(() => buildResourcePolicy({ ...budget, temporary_storage_mb: "2048" }, capacity));
});

test("GPU sandbox requires an available executor and explicitly detected device", () => {
  const policy = buildResourcePolicy({ ...budget, validation_mode: "sandbox", gpu_device_id: "GPU-test-123" }, capacity);
  assert.equal(policy.compute_target, "gpu");
  assert.deepEqual(policy.gpu_device_ids, ["GPU-test-123"]);
  assert.throws(() => buildResourcePolicy({ ...budget, validation_mode: "sandbox" }, { ...capacity, sandbox_ready: false }));
  assert.throws(() => buildResourcePolicy({ ...budget, validation_mode: "sandbox", gpu_device_id: "GPU-other" }, capacity));
});

test("API dispatch preserves the selected budget", async () => {
  const policy = buildResourcePolicy(budget, capacity);
  const api = new WorkbenchApi("/api", async (_url, options) => {
    assert.deepEqual(JSON.parse(options.body).validation_policy, policy);
    return new Response("{}", { status: 200 });
  });
  await api.start(7, "MNIST", undefined, policy);
});

test("form produces the backend search contract with deduplicated terms", () => {
  assert.deepEqual(buildSearchRequest(form), {
    topic: "Graph attention", description: "Graph attention", start_date: "2020-01-01",
    end_date: "2026-10-22", keywords: ["GAT", "node classification"],
    exclusion_keywords: [], venues: [], venue_quality: null, max_results: 5,
  });
});

test("ICORE is sent as the backend's core identifier", () => {
  assert.deepEqual(buildSearchRequest({ ...form, ranking_system: "core", allowed_levels: "A*, A" }).venue_quality,
    { ranking_system: "core", allowed_levels: ["A*", "A"] });
  assert.throws(() => buildSearchRequest({ ...form, ranking_system: "ccf", allowed_levels: "A*" }));
});

test("reject invalid dates, task IDs and excessive result counts before dispatch", () => {
  assert.throws(() => buildSearchRequest({ ...form, start_date: "2027-01-01" }));
  assert.throws(() => buildSearchRequest({ ...form, max_results: "21" }));
  for (const id of ["1e3", "-1", "0", "1.5", "9007199254740992", "1/selection"]) {
    assert.throws(() => parseRunId(id));
  }
});

test("paper-provided HTML and unsafe URLs cannot become executable content", () => {
  assert.equal(escapeHtml('<img onerror="evil()">'), "&lt;img onerror=&quot;evil()&quot;&gt;");
  for (const url of ["javascript:alert(1)", "data:text/html,test", "file:///etc/passwd", "https://user:pass@example.com/"]) {
    assert.equal(safeUrl(url), null);
  }
  assert.equal(safeUrl("https://github.com/test/repo"), "https://github.com/test/repo");
});

test("static passes and executed smoke tests never imply reproduced paper metrics", () => {
  const artifact = { status: "repository_ready", repository_url: "https://github.com/test/repo", commit_sha: "1234567" };
  assert.deepEqual(evidenceSummary(artifact, { mode: "static", status: "passed", code_executed: false }), {
    repository: true, candidate: false, staticPassed: true, codeExecuted: false, metricsReproduced: false,
  });
  assert.equal(evidenceSummary(artifact, { mode: "sandbox", status: "passed", code_executed: true }).metricsReproduced, false);
});

test("API start explicitly selects static verification without sandbox execution", async () => {
  let request;
  const api = new WorkbenchApi("/custom-api/", async (url, options) => {
    request = { url, ...options };
    return new Response(JSON.stringify({ literature_run_id: 7 }), { status: 200 });
  });
  api.token = "session-token";
  await api.start(7, "PyTorch");
  assert.equal(request.url, "/custom-api/literature/runs/7/workflow/start");
  assert.equal(request.headers.Authorization, "Bearer session-token");
  assert.deepEqual(JSON.parse(request.body), { code_requirements: "PyTorch", validation_policy: { mode: "static" } });
});

test("paper selection sends the chosen IDs once without automatically retrying mutations", async () => {
  let count = 0;
  const api = new WorkbenchApi("/api", async (_url, options) => {
    count++;
    assert.deepEqual(JSON.parse(options.body).selected_paper_ids, [2, 3]);
    return new Response(JSON.stringify({ detail: "queue unavailable" }), { status: 503 });
  });
  await assert.rejects(api.select(7, [2, 3], ""), (error) => error instanceof ApiError && error.status === 503);
  assert.equal(count, 1);
});

test("rate limit and validation errors retain actionable API details", async () => {
  const api = new WorkbenchApi("/api", async () => new Response(JSON.stringify({ detail: "rate limited" }), {
    status: 429, headers: { "Retry-After": "31" },
  }));
  await assert.rejects(api.request("/test"), (error) => error.retryAfter === 31 && error.status === 429);
});

test("only missing optional resources are suppressed; auth failures remain visible", async () => {
  const api = new WorkbenchApi("/api", async () => new Response("{}", { status: 404 }));
  assert.equal(await api.request("/test", { optional: true }), null);
  api.fetcher = async () => new Response("{}", { status: 401 });
  await assert.rejects(api.request("/test", { optional: true }), (error) => error.status === 401);
});

test("literature and code waits show stages without invented percentages", () => {
  const literature = workflowProgress({ run: { status: "running" }, workflow: { status: "waiting_for_literature" } });
  assert.equal(literature.phase, "working");
  assert.equal(literature.title, "正在检索文献");
  assert.equal(literature.completedStages, 0);
  const code = workflowProgress({ run: { status: "completed" }, workflow: { status: "waiting_for_code" } });
  assert.equal(code.stage, 2);
  assert.equal(code.title, "正在处理代码");
  assert.equal(code.completedStages, 2);
  assert.equal("percentage" in code, false);
});

test("manual paper selection is waiting for the user, not still processing", () => {
  const progress = workflowProgress({ run: { status: "completed" }, workflow: { status: "waiting_for_selection" } });
  assert.equal(progress.phase, "waiting");
  assert.equal(progress.title, "请选择论文");
  assert.equal(progress.completedStages, 1);
});

test("code dispatch completion alone does not count as code completion", () => {
  const progress = workflowProgress({ run: { status: "completed" }, workflow: { status: "waiting_for_code" }, nodes: [{ node: "code", status: "completed" }] });
  assert.equal(progress.done[2], false);
  assert.equal(progress.completedStages, 2);
});

test("validation starts after an observed code completion", () => {
  const progress = workflowProgress({ run: { status: "completed" }, workflow: { status: "running" }, nodes: [{ node: "code_wait", status: "completed" }] });
  assert.equal(progress.stage, 3);
  assert.equal(progress.title, "正在验证代码");
  assert.equal(progress.completedStages, 3);
});

test("terminal and offline states do not remain in a working phase", () => {
  for (const status of ["failed", "cancelled", "timed_out"]) {
    assert.equal(workflowProgress({ run: { status: "completed" }, workflow: { status } }).phase, status);
  }
  assert.equal(workflowProgress({ run: { status: "running" }, syncError: { status: 503 } }).phase, "unavailable");
  assert.equal(workflowProgress({ syncError: { status: 401 } }).title, "需要连接认证");
});

test("completed workflow does not claim a successful paper reproduction", () => {
  const progress = workflowProgress({ run: { status: "completed" }, workflow: { status: "completed" }, result: { validation_reports: [{ mode: "static", code_executed: false }] } });
  assert.equal(progress.phase, "complete");
  assert.equal(progress.completedStages, 4);
  assert.equal(progress.title, "流程已完成");
  assert.doesNotMatch(progress.title + progress.detail, /复现成功|训练完成/);
});

test("elapsed time uses recorded timestamps and freezes at completion", () => {
  const start = "2026-11-02T01:00:00Z";
  const finish = "2026-11-02T01:03:22Z";
  assert.equal(elapsedTime(start, finish, Date.parse("2026-11-02T02:00:00Z")), "03:22");
  assert.equal(elapsedTime(start, null, Date.parse(finish)), "03:22");
  assert.equal(elapsedTime(null, null), "—");
});
