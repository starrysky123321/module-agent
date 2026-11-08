import {
  WorkbenchApi, buildResourcePolicy, buildSearchRequest, escapeHtml as e,
  evidenceSummary, formatDuration, parseRunId, safeUrl,
  workflowProgress, elapsedTime, paperIntegrityDisplay, repositoryOriginNote,
} from "./core.mjs";
import { chineseMessage, chineseWarnings, artifactOutcome, hasChinese, legacyPlanOutline, dependencyDisplay } from "./locale-zh.mjs";
import { ExperimentPanel } from "./experiments.mjs";

const $ = (id) => document.getElementById(id);
const api = new WorkbenchApi();
const experiments = new ExperimentPanel($("experiments-panel"), api, (message) => showNotice(message));
const STORAGE_KEY = "module-agent.workbench.history.v1";
const TERMINAL = new Set(["completed", "failed", "cancelled", "timed_out"]);
const labels = {
  pending: "尚未启动", queued: "排队中", running: "执行中", completed: "流程完成",
  waiting_for_literature: "正在检索文献", waiting_for_selection: "等待论文确认",
  waiting_for_code: "等待代码处理", failed: "失败", cancelled: "已取消", timed_out: "已超时",
  passed: "通过", partial: "检查有提醒", warning: "提醒", skipped: "已跳过", interrupted: "暂停等待",
  official: "官方仓库", author: "作者仓库", third_party: "第三方实现", unknown: "证据不足",
  reproduction_plan: "复现方案", repository_ready: "仓库已获取", reproduction_planned: "复现方案已生成",
  open_source: "有开源许可证", source_available: "代码公开", not_found: "未找到代码",
  static: "静态检查", sandbox: "沙箱验证", success: "成功",
  timeout: "超时", error: "错误", empty: "无结果", empty_result: "无结果", rate_limited: "被限流", circuit_open: "来源暂时熔断",
};
const nodeLabels = {
  supervisor: "流程协调 · 决策", literature_dispatch: "文献检索 · 派发任务",
  literature_wait: "文献检索 · 等待结果", paper_selection: "人工确认 · 论文选择",
  code: "代码处理 · 获取或生成代码", code_wait: "代码处理 · 等待结果",
  validation: "产物验证 · 执行检查", finish: "流程协调 · 汇总结果",
};
const checkNames = {
  workspace: "工作目录", git_commit: "代码版本", readme: "项目说明", license: "许可证",
  dependency_manifest: "依赖清单", artifact_contract: "产物结构", reproduction_plan: "复现方案",
  security_scan: "安全扫描", syntax: "语法检查", import: "模块导入", smoke_test: "冒烟测试",
  project_tests: "仓库测试", dependency_install: "依赖安装",
};
let history = readHistory();
let state = null;
let pollTimer;
let controller = new AbortController();
let busy = false;
let retryDelay = 8000;
let papersSignature = "";
let timelineSignature = "";
let resultsSignature = "";
let selected = new Set();
let resources = null;
let detectingResources = false;
let resourceController;
let currentProgress = null;
let paperViewStatus = "";
let resourceBudgetEdited = false;
let healthController;

function resourceFeedback(status, message) {
  $("resource-feedback").dataset.state = status;
  $("resource-status").textContent = message;
  $("retry-resources").hidden = status !== "error";
}

function setSidebar(open) {
  document.body.classList.toggle("sidebar-open", open);
  $("sidebar-backdrop").hidden = !open;
  $("menu-toggle").setAttribute("aria-expanded", String(open));
  if (open) $("new-task").focus();
}

function sizeLabel(mb) {
  return mb == null ? "未知" : mb >= 1024 ? `${(mb / 1024).toFixed(1)} GiB` : `${mb} MiB`;
}

async function detectResources() {
  resourceController?.abort();
  const current = new AbortController();
  resourceController = current;
  detectingResources = true;
  $("detect-resources").disabled = true;
  $("resource-message").textContent = "正在检测当前服务的资源…";
  resourceFeedback("loading", "正在检测资源，不影响默认静态流程。");
  $("resource-budget-summary").textContent = "正在检测";
  updateBusy();
  try {
    const snapshot = await api.request("/system/resources", { signal: AbortSignal.any([current.signal, AbortSignal.timeout(12000)]) });
    if (current.signal.aborted) return;
    const firstDetection = !resources;
    resources = snapshot;
    const scope = { container: "Docker 容器", wsl: "WSL 环境", host: "当前主机" }[snapshot.scope] || snapshot.scope;
    $("resource-scope").textContent = `${scope} · ${dateLabel(snapshot.detected_at)} · 非浏览器硬件`;
    $("resource-summary").innerHTML = [
      ["可用 CPU", `${snapshot.available_cpu_count} 核`],
      ["可用内存", sizeLabel(snapshot.memory_available_mb)],
      ["磁盘剩余", sizeLabel(snapshot.workspace_free_mb)],
      ["可见 GPU", snapshot.gpu_status === "detected" ? `${snapshot.gpus.length} 张` : snapshot.gpu_status === "not_detected" ? "未检测到" : "无法查询"],
    ].map(([name, value]) => `<div><small>${name}</small><strong>${e(value)}</strong></div>`).join("");
    $("gpu-summary").textContent = snapshot.gpus.length
      ? snapshot.gpus.map((gpu) => `GPU ${gpu.index} · ${gpu.name} · 总显存 ${sizeLabel(gpu.memory_total_mb)} / 可用 ${sizeLabel(gpu.memory_free_mb)}`).join("；")
      : snapshot.gpu_status === "unavailable" ? "当前环境无法查询 NVIDIA GPU，这不代表宿主机没有显卡。" : "当前环境未枚举到 NVIDIA GPU。";
    $("cpu-limit").max = Math.min(8, snapshot.available_cpu_count);
    $("memory-limit").max = Math.min(16384, snapshot.memory_available_mb ?? 16384);
    $("workspace-limit").max = Math.min(65536, snapshot.workspace_free_mb ?? 65536);
    if (firstDetection && !resourceBudgetEdited) {
      $("cpu-limit").value = Math.max(0.1, Math.floor(Math.min(2, snapshot.available_cpu_count) * 20) / 20);
      $("memory-limit").value = Math.max(128, Math.floor(Math.min(1024, snapshot.memory_available_mb ?? 1024) / 128) * 128);
      $("workspace-limit").value = Math.max(128, Math.floor(Math.min(2048, snapshot.workspace_free_mb ?? 2048) / 128) * 128);
      $("temporary-storage").value = Math.min(512, Number($("memory-limit").value));
    }
    const gpuSelect = $("gpu-device");
    const previousGpu = gpuSelect.value;
    gpuSelect.innerHTML = '<option value="">CPU</option>' + (snapshot.gpus || []).map((gpu) => `<option value="${e(gpu.uuid)}">GPU ${gpu.index} · ${e(gpu.name)} · 可用显存 ${sizeLabel(gpu.memory_free_mb)}</option>`).join("");
    if (snapshot.gpus.some((gpu) => gpu.uuid === previousGpu)) gpuSelect.value = previousGpu;
    $("execution-mode").querySelector('[value="sandbox"]').disabled = !snapshot.sandbox_ready;
    if (!snapshot.sandbox_ready) $("execution-mode").value = "static";
    $("resource-message").innerHTML = localized(snapshot.sandbox_reason, "运行环境已检测，沙箱可用性以当前设置为准。");
    resourceFeedback("success", "资源检测完成，可在设置中调整预算。");
    updateResourceMode();
  } catch (error) {
    if (current.signal.aborted) return;
    resources = null;
    $("resource-message").innerHTML = error.status === 401 ? "需要认证：请在连接设置填写 Token 后重新检测。" : localized(error.message, "资源检测失败，请重试。");
    resourceFeedback("error", error.status === 401 ? "资源检测需要认证，请在导航的连接设置填写 Token。" : "资源检测失败；默认静态流程仍可提交，自定义预算需重试检测。");
    $("resource-budget-summary").textContent = "检测失败";
    $("resource-summary").innerHTML = "";
    $("gpu-summary").textContent = "";
    $("execution-mode").querySelector('[value="sandbox"]').disabled = true;
    $("gpu-device").disabled = true;
  } finally {
    if (resourceController === current) {
      detectingResources = false;
      $("detect-resources").disabled = busy;
      updateBusy();
    }
  }
}

function updateResourceMode() {
  const sandbox = $("execution-mode").value === "sandbox";
  $("gpu-device").disabled = !sandbox || !resources?.gpus?.length;
  $("temporary-storage").max = Number($("memory-limit").value);
  if (Number($("temporary-storage").value) > Number($("memory-limit").value)) {
    $("temporary-storage").value = $("memory-limit").value;
  }
  $("sandbox-state").textContent = sandbox
    ? "沙箱进行语法检查，网络关闭，不会自动训练模型。"
    : "静态检查不会启动沙箱；工作区空间仍按预算监测。";
  $("execution-hint").textContent = sandbox ? "仅做沙箱语法检查，不执行训练" : "仅做静态检查，不执行训练";
  updateBudgetSummary();
}

function updateBudgetSummary() {
  if (resources) $("resource-budget-summary").textContent = `CPU ${$("cpu-limit").value} 核 · 内存 ${sizeLabel(Number($("memory-limit").value))} · 空间 ${sizeLabel(Number($("workspace-limit").value))}`;
}

function readHistory() {
  try {
    const items = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    return Array.isArray(items) ? items.filter((item) => Number.isSafeInteger(item?.id) && item.id > 0 && typeof item.topic === "string").slice(0, 20) : [];
  } catch { return []; }
}

function remember(run) {
  history = [{ id: run.id, topic: run.request.topic, date: run.created_at }, ...history.filter((item) => item.id !== run.id)].slice(0, 20);
  persistHistory();
  renderHistory();
}

function persistHistory() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(history)); return true; }
  catch { return false; /* Browser storage is optional. */ }
}

async function deleteTasks(ids) {
  if (busy || !ids.length) return;
  const targets = [...new Set(ids.map(parseRunId))];
  if (!window.confirm(`确定永久删除${targets.length === 1 ? `任务 #${targets[0]}` : `本列表中的 ${targets.length} 个任务（${targets.map((id) => `#${id}`).join("、")}）`}及关联结果、恢复断点？此操作无法从界面撤销。执行中的任务不会被删除。共享论文与已下载的工作区文件不受影响。`)) return;
  busy = true;
  clearTimeout(pollTimer);
  if (state && targets.includes(state.id)) {
    controller.abort();
    controller = new AbortController();
    state.refreshing = false;
    state.refreshAgain = false;
  }
  updateBusy();
  showNotice("");
  const deleted = new Set();
  const errors = [];
  try {
    for (const id of targets) {
      try { await api.remove(id); deleted.add(id); }
      catch (error) { errors.push({ id, message: chineseMessage(error.message, "删除未完成，请重试或查看原始错误。") }); }
    }
    // Only remove list entries after the backend confirms actual deletion.
    history = history.filter((item) => !deleted.has(item.id));
    const saved = persistHistory();
    if (state && deleted.has(state.id)) {
      busy = false;
      showCreate();
      busy = true;
    }
    renderHistory();
    showNotice(`${deleted.size ? targets.length === 1 ? `任务 #${targets[0]} 已删除。` : `已删除 ${deleted.size} 个任务。` : ""}${errors.length ? `未完成删除：${errors.map((error) => `#${error.id}：${error.message.text}`).join("；")}` : ""}${saved ? "" : " 浏览器未允许更新本地列表，请刷新后重试。"}`, errors.length ? "error" : saved ? "success" : "warning");
    const originals = errors.filter((error) => error.message.original).map((error) => `#${error.id}：${error.message.original}`);
    if (originals.length) $("notice").insertAdjacentHTML("beforeend", originalText(originals.join("\n\n"), "查看原始错误"));
  } finally {
    busy = false;
    updateBusy();
    if (state) schedulePoll(controller.signal);
    else $("topic").focus();
  }
}

function renderHistory() {
  $("history-count").textContent = history.length;
  $("clear-history").hidden = !history.length;
  $("clear-history").disabled = busy;
  $("history-list").innerHTML = history.length ? history.map((item) => `
    <div class="history-entry ${state?.id === item.id ? "selected" : ""}">
      <button class="history-item" data-run="${item.id}" title="${e(item.topic)}" ${busy ? "disabled" : ""}>
        <span>${e(item.topic)}</span><small>#${item.id} · ${e(dateLabel(item.date))}</small>
      </button>
      <button type="button" class="history-remove" data-remove-history="${item.id}" aria-label="删除任务 #${item.id}" title="永久删除任务及关联记录" ${busy ? "disabled" : ""}><svg class="action-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true" focusable="false"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 10v7m4-7v7"/></svg></button>
    </div>`).join("") : '<p class="sidebar-empty">暂无记录</p>';
}

function dateLabel(value) {
  if (!value) return "时间未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间未记录" : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function badge(value, text = labels[value] || value) {
  const color = ["completed", "passed", "success", "official", "open_source"].includes(value) ? "green"
    : ["failed", "cancelled"].includes(value) ? "red"
    : ["warning", "partial", "skipped", "unknown", "timed_out", "reproduction_planned"].includes(value) ? "amber" : "blue";
  return `<span class="badge ${color}">${e(text)}</span>`;
}

function link(url, text) {
  const target = safeUrl(url);
  return target ? `<a href="${e(target)}" target="_blank" rel="noopener noreferrer">${e(text)} ↗</a>` : "";
}

function showNotice(message, kind = "error") {
  $("notice").className = `notice ${kind}`;
  $("notice").textContent = message;
  $("notice").hidden = !message;
}

function handleError(error) {
  if (error.name === "AbortError") return;
  const prefix = error.status === 401 ? "API 需要认证，请在导航的「连接设置」填写 Token。"
    : error.status === 429 ? "请求被限流，已延后同步。"
    : error instanceof TypeError ? "无法连接服务，请检查 API 是否运行。" : "";
  const message = chineseMessage(error.message, "操作未完成，请查看原始错误信息或重试。");
  showNotice(`${prefix}${prefix ? " " : ""}${message.text}`);
  if (message.original) $("notice").insertAdjacentHTML("beforeend", originalText(message.original, "查看原始错误"));
  if (error.status === 429) retryDelay = Math.max(error.retryAfter * 1000, 30000);
}

function resetRequests() {
  experiments.close();
  clearTimeout(pollTimer);
  controller.abort();
  controller = new AbortController();
  papersSignature = timelineSignature = resultsSignature = "";
  selected = new Set();
  currentProgress = null;
  paperViewStatus = "";
  return controller.signal;
}

function showCreate() {
  if (busy) return;
  resetRequests();
  state = null;
  $("new-task").classList.add("active");
  $("new-task").setAttribute("aria-current", "page");
  setSidebar(false);
  $("create-view").hidden = false;
  $("run-view").hidden = true;
  showNotice("");
  window.history.replaceState(null, "", window.location.pathname);
  renderHistory();
  $("topic").focus();
}

async function checkHealth() {
  healthController?.abort();
  const current = new AbortController();
  healthController = current;
  $("health").className = "health";
  $("health").dataset.state = "loading";
  $("health-text").textContent = "正在连接";
  $("retry-connection").hidden = true;
  try {
    const health = await api.request("/health/ready", { signal: AbortSignal.any([current.signal, AbortSignal.timeout(6000)]) });
    if (current.signal.aborted) return;
    if (health.status !== "ready") throw new Error("服务尚未就绪");
    $("health").className = "health good";
    $("health").dataset.state = "success";
    $("health-text").textContent = "服务已就绪";
  } catch (error) {
    if (current.signal.aborted) return;
    $("health").className = "health bad";
    $("health").dataset.state = "error";
    $("health-text").textContent = error.status === 401 ? "需要连接认证" : "服务未就绪";
    $("health").title = error.message;
    $("retry-connection").hidden = false;
  }
}

function runPath(suffix = "") { return `/literature/runs/${state.id}${suffix}`; }
function workflowPath(suffix = "") { return `/workflow/runs/${state.id}${suffix}`; }

async function openRun(value, { requirements = "", refresh = true, policy = null, rememberHistory = true } = {}) {
  if (busy) return;
  const id = parseRunId(value);
  const signal = resetRequests();
  state = { id, run: null, workflow: null, papers: [], nodes: [], result: null, requirements, policy, rememberOnLoad: rememberHistory };
  $("delete-run").disabled = false;
  $("new-task").classList.remove("active");
  $("new-task").removeAttribute("aria-current");
  setSidebar(false);
  $("selection-requirements").value = requirements;
  $("create-view").hidden = true;
  $("run-view").hidden = false;
  $("run-title").textContent = `正在读取任务 #${id}…`;
  $("run-description").textContent = "";
  $("run-eyebrow").textContent = `任务 #${id}`;
  $("run-meta").textContent = "";
  $("run-controls").textContent = "";
  $("results-panel").hidden = true;
  $("papers-panel").hidden = true;
  $("warnings-panel").hidden = true;
  $("show-warnings").hidden = true;
  $("run-settings").open = false;
  $("execution-details").open = false;
  $("selection-footer").hidden = true;
  $("papers-list").innerHTML = empty("读取任务中的论文…");
  $("timeline").innerHTML = empty("读取节点执行记录…");
  $("agent-progress").innerHTML = "";
  $("search-details").textContent = "等待数据";
  $("run-warnings").textContent = "等待数据";
  $("run-resources").textContent = "正在读取任务预算…";
  $("export-run").disabled = true;
  showNotice("");
  window.history.replaceState(null, "", `#run=${id}`);
  renderHistory();
  renderProgress();
  if (refresh) await refreshRun(signal);
}

function schedulePoll(signal) {
  clearTimeout(pollTimer);
  if (!signal.aborted && state && !TERMINAL.has(state.workflow?.status) && !["failed", "cancelled"].includes(state.run?.status)) {
    pollTimer = setTimeout(() => refreshRun(signal), retryDelay);
  }
}

async function refreshRun(signal = controller.signal) {
  if (!state || signal.aborted || busy) return;
  const current = state;
  if (current.refreshing) {
    current.refreshAgain = true;
    return;
  }
  current.refreshing = true;
  current.stopPolling = false;
  clearTimeout(pollTimer);
  $("poll-status").textContent = "正在同步后端状态…";
  try {
    const run = await api.request(runPath(), { signal });
    const workflow = await api.request(workflowPath(), { signal, optional: true });
    if (signal.aborted || state !== current) return;
    current.run = run;
    current.workflow = workflow;
    if (current.rememberOnLoad) {
      remember(run);
      current.rememberOnLoad = false;
    }
    const jobs = [
      workflow ? api.request(workflowPath("/nodes"), { signal }) : Promise.resolve([]),
      run.status === "completed" ? api.request(runPath("/papers"), { signal }) : Promise.resolve([]),
      workflow ? api.request(workflowPath("/resources"), { signal, optional: true }) : Promise.resolve(null),
    ];
    const [nodes, papers, policy] = await Promise.allSettled(jobs);
    if (signal.aborted || state !== current) return;
    if (nodes.status === "fulfilled") current.nodes = nodes.value;
    else if (nodes.reason.name !== "AbortError") handleError(nodes.reason);
    if (papers.status === "fulfilled") current.papers = papers.value;
    else if (papers.reason.name !== "AbortError") handleError(papers.reason);
    if (policy.status === "fulfilled" && policy.value) current.policy = policy.value;
    else if (policy.status === "rejected" && policy.reason.name !== "AbortError") handleError(policy.reason);
    if (workflow && ["completed", "failed", "cancelled"].includes(workflow.status)) {
      try {
        current.result = await api.request(workflowPath("/result"), { signal });
        if (current.result.validation_policy) current.policy = current.result.validation_policy;
      }
      catch (error) {
        if (error.status !== 409 && error.status !== 404) throw error;
        current.resultNote = "后端尚未提供最终产物，可刷新重试；任务状态不代表实验复现成功。";
      }
    }
    if (signal.aborted || state !== current) return;
    current.syncError = null;
    renderRun();
    retryDelay = 8000;
    const stopped = TERMINAL.has(workflow?.status) || ["failed", "cancelled"].includes(run.status);
    $("poll-status").textContent = `${new Date().toLocaleTimeString("zh-CN")} 已同步${stopped ? "" : " · 每 8 秒更新"}`;
  } catch (error) {
    if (signal.aborted || state !== current) return;
    handleError(error);
    current.syncError = { status: error.status, message: error.message };
    renderProgress();
    $("poll-status").textContent = "同步失败，可手动刷新或等待重试。";
    if (error.status === 401 || error.status === 404) {
      current.stopPolling = true;
      return;
    }
  } finally {
    current.refreshing = false;
    if (state === current && !signal.aborted && current.refreshAgain && !busy) {
      current.refreshAgain = false;
      queueMicrotask(() => refreshRun(signal));
    }
  }
  if (!current.stopPolling) schedulePoll(signal);
}

function empty(title, subtitle = "") {
  return `<div class="empty-state"><span class="empty-icon" aria-hidden="true">▤</span>${e(title)}${subtitle ? `<p>${e(subtitle)}</p>` : ""}</div>`;
}

function renderRun() {
  const { run, workflow, id, result } = state;
  if (!run) return;
  $("run-title").textContent = run.request.topic;
  $("run-description").textContent = run.request.description !== run.request.topic ? run.request.description : "";
  $("run-meta").innerHTML = `<span>创建于 ${e(dateLabel(run.created_at))}</span><span>检索范围 ${e(run.request.start_date)} — ${e(run.request.end_date)}</span>`;
  $("trace-id").textContent = workflow?.trace_id ? `任务 #${id} · 追踪标识：${workflow.trace_id}` : "";
  const controls = [];
  if (!workflow && ["pending", "queued", "running"].includes(run.status)) {
    controls.push('<button class="button primary" data-action="start">继续启动任务</button>');
  }
  if (run.status === "completed" && (!workflow || workflow.status === "waiting_for_literature")) {
    controls.push(`<button class="button primary" data-action="enter-selection">进入论文选择</button>`);
  }
  if (workflow?.status === "timed_out") controls.push('<button class="button primary" data-action="resume">恢复任务</button>');
  if (workflow && !TERMINAL.has(workflow.status)) controls.push('<button class="button danger-button" data-action="cancel">取消任务</button>');
  $("run-controls").innerHTML = controls.join("");
  $("export-run").disabled = false;
  renderPapers();
  renderTimeline();
  renderProgress();
  renderSearchDetails();
  renderResults();
  experiments.open(id, workflow?.status);
  const policy = state.policy;
  $("run-resources").innerHTML = policy ? `<p>${e(labels[policy.mode] || policy.mode)}${!workflow ? " · 尚未保存" : " · 已保存"}<br>CPU ≤ ${e(policy.cpu_limit)} 核<br>内存 ≤ ${sizeLabel(policy.memory_limit_mb)}<br>任务工作区 ≤ ${sizeLabel(policy.workspace_limit_mb)}（监测）<br>沙箱 /tmp ≤ ${sizeLabel(policy.temporary_storage_mb)}<br>单次沙箱检查 ≤ ${e(policy.timeout_seconds)} 秒<br>设备：${policy.gpu_device_ids?.length ? e(policy.gpu_device_ids.join("、")) : e(policy.compute_target || "cpu")}</p><p class="field-hint">CPU、内存和 /tmp 限额只在沙箱中生效；工作区为监测式限额。</p>` : '<p>此任务没有保存资源预算。</p>';
  const warnings = chineseWarnings(run.warnings || [], result?.warnings || [], (result?.validation_reports || []).flatMap((report) => report.warnings || []), [run.error, workflow?.error, state.resultNote]);
  $("warnings-panel").hidden = !warnings.length;
  $("warning-count").textContent = warnings.length;
  $("show-warnings").hidden = !warnings.length;
  $("show-warnings").textContent = `${warnings.length} 条提醒`;
  $("run-warnings").innerHTML = warningItems(warnings);
  updateBusy();
}

function renderPapers() {
  const selecting = state.workflow?.status === "waiting_for_selection";
  $("papers-panel").hidden = !state.papers.length && state.run.status !== "completed";
  const viewStatus = state.workflow?.status || state.run.status;
  if (viewStatus !== paperViewStatus) {
    $("papers-panel").open = selecting || !state.workflow || state.workflow.status === "waiting_for_literature";
    paperViewStatus = viewStatus;
  }
  const sig = JSON.stringify([state.papers, selecting]);
  $("paper-count").textContent = state.papers.length;
  $("papers-description").textContent = selecting ? "勾选论文后，点击下方确认按钮。" : state.papers.length ? `本次检索得到 ${state.papers.length} 篇论文。` : "没有符合条件的论文，可调整检索条件再试。";
  if (sig !== papersSignature) {
    papersSignature = sig;
    $("papers-list").innerHTML = state.papers.length ? state.papers.map((paper) => {
      const profile = paper.method_profile;
      const integrity = paperIntegrityDisplay(paper);
      if (integrity.blocked) selected.delete(paper.id);
      return `<article class="paper-card"><div class="paper-main">
        ${selecting && paper.id ? `<input type="checkbox" data-paper="${paper.id}" aria-label="选择 ${e(paper.title)}" ${integrity.blocked ? "disabled" : ""} ${selected.has(paper.id) ? "checked" : ""}>` : ""}
        <div class="paper-body"><h3 class="paper-title">${e(paper.title)}</h3>
          <p class="paper-authors">${e((paper.authors || []).slice(0, 3).join(" · ") || "作者未提供")}${paper.authors?.length > 3 ? " 等" : ""} · ${e(paper.publication_year || "年份未提供")}${paper.venue_name ? ` · ${e(paper.venue_name)}` : ""}</p>
          <div class="paper-tags"><span class="badge ${integrity.tone}" title="${e(integrity.note)}">${e(integrity.label)}</span></div>
          ${paper.integrity?.warnings?.length ? `<details class="paper-details"><summary>元数据核验说明</summary><p>${e(integrity.note)}</p>${paper.integrity.warnings.map((warning) => `<p>${e(warning)}</p>`).join("")}</details>` : ""}
          ${paper.relevance_reason ? `<div class="relevance-reason">${localized(paper.relevance_reason, "此论文的历史相关性说明为英文，可展开查看原文。")}</div>` : ""}
          <div class="paper-links">${link(paper.landing_page_url, "原文")}${link(paper.pdf_url, "PDF")}${paper.doi ? link(/^https?:\/\//i.test(paper.doi) ? paper.doi : `https://doi.org/${paper.doi}`, "DOI") : ""}</div>
          ${paper.abstract || profile ? `<details class="paper-details"><summary>摘要与方法</summary>${paper.abstract ? originalText(paper.abstract, "论文摘要原文") : ""}${profile ? `<dl>${[
            ["研究问题", profile.research_problem], ["模块类型", profile.module_type], ["核心方法", profile.core_method],
            ["输入", profile.inputs?.join("、")], ["输出", profile.outputs?.join("、")],
          ].filter(([, value]) => value).map(([key, value]) => `<dt>${key}</dt><dd>${localized(value)}</dd>`).join("")}</dl>${(profile.evidence || []).map((item) => originalText(item.excerpt, `原文依据（${item.field === "title" ? "标题" : "摘要"}）`)).join("")}` : ""}</details>` : ""}
        </div></div></article>`;
    }).join("") : empty("没有符合条件的论文", "可以扩大时间范围，或减少筛选条件。");
  }
  $("selection-footer").hidden = !selecting || !state.papers.length;
  updateSelection();
}

function updateSelection() {
  $("selection-count").textContent = `已选择 ${selected.size} 篇 / 最多 20 篇`;
  $("confirm-selection").disabled = busy || !selected.size || selected.size > 20;
}

function renderTimeline() {
  const sig = JSON.stringify(state.nodes);
  if (sig === timelineSignature) return;
  timelineSignature = sig;
  $("timeline").innerHTML = state.nodes.length ? state.nodes.map((node) => `
    <article class="timeline-item"><span class="timeline-mark">${node.status === "failed" ? "!" : node.status === "interrupted" ? "Ⅱ" : "✓"}</span>
    <div><h3>${e(nodeLabels[node.node] || node.node)} ${badge(node.status)}</h3><p>第 ${e(node.attempt)} 次 · ${e(dateLabel(node.created_at))}</p>${node.error ? `<div class="error-text">${localized(node.error, "此节点执行失败，请查看原始原因。")}</div>` : ""}
    <details><summary>输入 / 输出摘要</summary><pre>${e(JSON.stringify({ input: node.input_summary, output: node.output_summary }, null, 2))}</pre></details></div><span class="duration">${formatDuration(node.duration_ms)}</span></article>`).join("") : empty("还没有节点执行记录", "启动工作流后，后端记录的节点会显示在这里。");
}

function renderProgress() {
  currentProgress = workflowProgress(state || {});
  const progress = currentProgress;
  const phases = { working: "进行中", queued: "排队中", waiting: "等待你确认", complete: "已完成", failed: "失败", cancelled: "已取消", timed_out: "已超时", unavailable: "未同步", idle: "未启动" };
  const phaseBadge = $("progress-state");
  phaseBadge.textContent = phases[progress.phase] || "处理中";
  phaseBadge.className = `badge ${progress.phase === "complete" ? "green" : ["failed", "cancelled", "timed_out"].includes(progress.phase) ? "red" : progress.phase === "waiting" ? "amber" : "blue"}`;
  if ($("progress-title").textContent !== progress.title) $("progress-title").textContent = progress.title;
  $("progress-description").textContent = chineseMessage(progress.detail, "任务暂时未能继续，请查看提醒或运行记录中的原始原因。").text;
  const bar = $("run-progress");
  bar.dataset.mode = progress.phase;
  bar.dataset.step = progress.completedStages;
  bar.setAttribute("aria-valuetext", `${progress.title}，已完成 ${progress.completedStages} 个阶段`);
  if (["working", "queued", "unavailable"].includes(progress.phase)) bar.removeAttribute("aria-valuenow");
  else bar.setAttribute("aria-valuenow", progress.completedStages);
  $("progress-completed").textContent = `已完成 ${progress.completedStages} / 4 阶段`;
  const active = ["working", "queued", "waiting"].includes(progress.phase);
  $("agent-progress").innerHTML = ["检索文献", "选择论文", "处理代码", "验证结果"].map((name, index) => {
    const done = progress.done[index];
    return `<div class="agent-step ${done ? "done" : active && index === progress.stage ? "current" : ""}"><span class="agent-dot">${done ? "✓" : index + 1}</span>${name}</div>`;
  }).join("");
  updateElapsed();
}

function updateElapsed() {
  $("progress-elapsed").textContent = state && currentProgress?.startedAt ? `总用时 ${elapsedTime(currentProgress.startedAt, currentProgress.finishedAt)}` : "";
}

function originalText(value, label = "查看原文") {
  return `<details class="source-original"><summary>${e(label)}</summary><pre class="code-block">${e(typeof value === "string" ? value : JSON.stringify(value, null, 2))}</pre></details>`;
}

function localized(value, fallback) {
  const message = chineseMessage(value, fallback);
  return `<span class="localized-text">${e(message.text)}</span>${message.original ? originalText(message.original) : ""}`;
}

function warningItems(groups) {
  return groups.map((group) => `<div class="warning-item"><p>${e(group.text)}</p>${group.originals.length ? originalText(group.originals.join("\n\n")) : ""}</div>`).join("");
}

function renderPlan(plan) {
  const legacy = !hasChinese(plan.research_problem);
  const steps = legacy ? legacyPlanOutline(plan) : plan.implementation_steps;
  const list = (items) => `<ul class="readable-list">${items.map((item) => `<li>${localized(item)}</li>`).join("")}</ul>`;
  return `<div class="readable-details">${legacy ? '<p class="field-hint">以下为历史英文方案的中文要点，并非逐句译文。完整内容保留在原文中。</p>' : ""}
    <h4>研究问题</h4><div>${localized(plan.research_problem)}</div>
    <h4>建议步骤（尚未执行）</h4>${list(steps || [])}
    ${plan.inputs?.length ? `<h4>需要的输入</h4>${list(plan.inputs)}` : ""}
    ${plan.outputs?.length ? `<h4>预期输出（不代表已经生成）</h4>${list(plan.outputs)}` : ""}
    ${plan.suggested_dependencies?.length ? `<h4>建议依赖（尚未安装）</h4><p>${plan.suggested_dependencies.map((item) => `<code>${e(dependencyDisplay(item))}</code>`).join(" ")}</p>` : ""}
    ${plan.open_questions?.length ? `<h4>仍需确认</h4>${warningItems(chineseWarnings(plan.open_questions))}` : ""}
    ${originalText(plan, "完整方案原始数据")}</div>`;
}

function renderAnalysis(analysis) {
  const fields = [["依赖清单文件", "dependency_files"], ["依赖包", "dependencies"], ["入口文件", "entrypoints"], ["候选算法模块", "module_candidates"], ["数据集引用", "dataset_references"], ["权重引用", "weight_references"]];
  return `<div class="readable-details">${fields.filter(([, key]) => analysis[key]?.length).map(([label, key]) => `<h4>${label}</h4><ul class="readable-list">${analysis[key].map((value) => `<li><code>${e(value)}</code></li>`).join("")}</ul>`).join("")}${analysis.requirement_matches?.length ? `<h4>需求匹配说明</h4>${analysis.requirement_matches.map((value) => `<div>${localized(value)}</div>`).join("")}` : ""}${warningItems(chineseWarnings(analysis.warnings || []))}${originalText(analysis, "仓库分析原始数据")}</div>`;
}

function renderSearchDetails() {
  const run = state.run;
  $("search-details").innerHTML = `<p>检索词</p>${run.search_queries.length ? run.search_queries.map((query) => `<span class="badge">${e(query)}</span>`).join("") : '<p>尚未生成检索词</p>'}
    ${run.source_metrics?.length ? `<details class="paper-details"><summary>来源调用 · ${run.source_metrics.length} 次</summary>${run.source_metrics.map((metric) => `<p>${e(metric.source)} · ${badge(metric.outcome)}<br>${e(metric.query)}<br>${metric.result_count} 篇 · ${formatDuration(metric.duration_ms)}${metric.error_type ? `<br>${e(metric.error_type)}` : ""}</p>`).join("")}</details>` : ""}
    ${run.llm_metrics?.length ? `<details class="paper-details"><summary>模型调用 · ${run.llm_metrics.length} 次</summary><pre class="code-block">${e(JSON.stringify(run.llm_metrics, null, 2))}</pre></details>` : ""}`;
}

function renderResults() {
  const result = state.result;
  $("results-panel").hidden = !result;
  if (!result) return;
  const sig = JSON.stringify(result);
  if (resultsSignature === sig) return;
  resultsSignature = sig;
  $("results-list").innerHTML = (result.code_artifacts || []).map((artifact) => {
    const paper = result.selected_papers?.find((item) => item.paper_id === artifact.paper_id);
    const report = result.validation_reports?.find((item) => item.paper_id === artifact.paper_id);
    const evidence = evidenceSummary(artifact, report);
    const outcome = artifactOutcome(artifact, report);
    const originNote = repositoryOriginNote(artifact);
    const notes = chineseWarnings(artifact.warnings || [], artifact.reproduction_plan?.warnings || [], report?.warnings || [], [artifact.error, report?.error]);
    const mismatch = notes.find((note) => note.text.includes("候选结构与论文不一致"));
    const reportLabel = report?.checks?.every((check) => check.kind === "reproduction_plan") ? "方案检查" : labels[report?.mode] || "验证检查";
    const evidenceNames = { paper_url: "论文或页面提及了该仓库，不代表它是论文实现。", implementation_url: "论文明确声明的代码地址；是否对应该论文仍需结合仓库身份核对。", implementation_claim: "仓库声称实现该论文，但尚不能据此确认作者或官方身份。", doi: "仓库内容包含论文 DOI。", title: "仓库内容包含论文标题。", citation: "仓库引用了该论文。", author: "仓库账号与作者信息匹配。", keyword: "仓库内容与论文关键词匹配。" };
    return `<article class="artifact-card"><h3>${e(paper?.title || `论文 #${artifact.paper_id}`)}</h3>
      <div class="paper-tags">${badge(artifact.status)}<span class="badge ${outcome.color}">${e(outcome.label)}</span></div>
      <div class="result-guidance"><p>${e(outcome.next)}</p>${mismatch ? `<p class="error-text">${e(mismatch.text)}</p>` : ""}</div>
      ${artifact.repository_url ? `<p class="artifact-repo">${link(artifact.repository_url, artifact.repository_url)}</p>` : ""}
      <p class="report-boundary">${report?.mode === "static" ? "本次为静态检查，没有执行论文代码，尚未验证论文指标。" : report?.code_executed ? "本次执行了验证命令，尚无论文指标对照。" : "尚无论文代码执行记录或论文指标对照。"}</p>
      <details><summary class="details-label">代码来源与证据</summary>
      <p class="artifact-meta">来源判定：${e(originNote?.label || labels[artifact.origin] || artifact.origin)} · 规则匹配分 ${Math.round(artifact.confidence * 100)}/100（不代表正确率）</p>
      ${originNote ? `<p class="field-hint">${e(originNote.note)}</p>` : ""}
      <p class="artifact-meta">代码版本 <code>${e(artifact.commit_sha || "未获取")}</code> · 许可证 ${e(artifact.license_spdx || "未识别")}</p>
      ${artifact.local_path ? `<p class="artifact-meta">服务端工作区：${e(artifact.local_path)}</p>` : ""}
      ${artifact.evidence?.length ? `<ul class="artifact-evidence">${artifact.evidence.map((item) => `<li>${localized(item.description, evidenceNames[item.evidence_type] || "此条为仓库匹配证据，可展开查看原文。")} ${item.source_url ? link(item.source_url, "来源") : ""}</li>`).join("")}</ul>` : ""}
      ${artifact.llm_metrics?.length ? `<details class="paper-details"><summary>代码阶段模型调用 · ${artifact.llm_metrics.length} 次</summary>${artifact.llm_metrics.map((metric) => `<p>${e(({reproduction_planning:"复现规划",reproduction_implementation:"候选代码生成"})[metric.stage] || metric.stage)} · ${e(metric.model)} · ${e(({success:"成功",failed:"失败",timeout:"已超时",cancelled:"已取消"})[metric.outcome] || metric.outcome)}<br>耗时 ${formatDuration(metric.duration_ms)} · Token：${e(metric.total_tokens ?? "服务商未返回")}</p>`).join("")}</details>` : ""}
      <div class="evidence-matrix">${[
        ["已获取并固定代码版本", evidence.repository], ["已生成候选实现", evidence.candidate],
        ["静态检查整体通过", evidence.staticPassed], ["验证阶段实际执行代码", evidence.codeExecuted],
      ].map(([text, yes]) => `<div class="evidence-row ${yes ? "yes" : ""}"><span>${yes ? "✓" : "—"}</span>${text} · ${yes ? "是" : "否"}</div>`).join("")}</div>
      </details>
      ${artifact.reproduction_plan ? `<details><summary class="details-label">复现计划与待确认问题</summary>${renderPlan(artifact.reproduction_plan)}</details>` : ""}
      ${artifact.repository_analysis ? `<details><summary class="details-label">依赖、入口与算法模块</summary>${renderAnalysis(artifact.repository_analysis)}</details>` : ""}
      ${report ? `<p class="report-summary">${e(reportLabel)}：${report.checks.filter((check) => check.status === "passed").length} 项通过${report.checks.some((check) => check.status === "warning") ? `，${report.checks.filter((check) => check.status === "warning").length} 项提醒` : ""}${report.checks.some((check) => check.status === "failed") ? `，${report.checks.filter((check) => check.status === "failed").length} 项失败` : ""}</p><details><summary class="details-label">检查明细</summary><table class="checks"><thead><tr><th scope="col">检查项</th><th scope="col">状态</th><th scope="col">说明</th></tr></thead><tbody>${report.checks.map((check) => `<tr><td>${e(checkNames[check.kind] || check.kind)}</td><td>${badge(check.status)}</td><td>${localized(check.summary, `此项检查${labels[check.status] || "已返回结果"}，可展开查看原始说明。`)}${check.command ? `<pre class="code-block">${e(check.command)}\n退出码：${e(check.exit_code ?? "未返回")}</pre>` : ""}</td></tr>`).join("")}</tbody></table></details>` : '<p class="artifact-meta">尚无验证报告。</p>'}
      ${notes.length ? `<details class="artifact-warnings"><summary class="details-label">注意事项（${notes.length}）</summary>${warningItems(notes)}</details>` : ""}
      ${originalText({ artifact, validation_report: report || null }, "技术详情（原始数据）")}
    </article>`;
  }).join("") || empty("当前结果没有代码产物", result.failure?.message || "可查看节点记录与工作流警告定位原因。");
}

function updateBusy() {
  $("create-button").disabled = busy;
  $("create-button").setAttribute("aria-busy", String(busy));
  $("search-form").setAttribute("aria-busy", String(busy));
  $("create-button").textContent = busy ? "正在提交…" : "开始检索";
  $("refresh-run").disabled = busy;
  $("delete-run").disabled = busy || !state;
  $("new-task").disabled = busy;
  $("open-run").disabled = busy;
  $("open-run-mobile").disabled = busy;
  $("detect-resources").disabled = busy || detectingResources;
  $("retry-resources").disabled = busy || detectingResources;
  document.querySelectorAll("#search-form input, #search-form textarea, #search-form select, .topic-example").forEach((field) => {
    if (busy) {
      if (!field.disabled) { field.dataset.busyDisabled = "true"; field.disabled = true; }
    } else if (field.dataset.busyDisabled) {
      field.disabled = false;
      delete field.dataset.busyDisabled;
    }
  });
  document.querySelectorAll("[data-action], [data-run], [data-remove-history], #clear-history").forEach((button) => { button.disabled = busy; });
  updateSelection();
}

async function mutate(operation) {
  if (busy) return;
  busy = true;
  clearTimeout(pollTimer);
  updateBusy();
  showNotice("");
  const current = state;
  try { await operation(); }
  catch (error) { handleError(error); }
  finally {
    busy = false;
    updateBusy();
    if (state === current && state) await refreshRun();
  }
}

$("search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  if (!validateSearchFields()) { $("topic").value.trim() ? $("end-date").focus() : $("topic").focus(); return; }
  let request;
  let policy;
  const values = Object.fromEntries(new FormData(event.currentTarget));
  try {
    request = buildSearchRequest(values);
    // The backend accepts its default static policy without resource admission.
    // Explicit budgets and sandbox execution must still use a real snapshot.
    policy = !resources && !resourceBudgetEdited && values.validation_mode === "static"
      ? { mode: "static" } : buildResourcePolicy(values, resources);
  } catch (error) { handleError(error); return; }
  busy = true;
  updateBusy();
  showNotice("");
  const signal = resetRequests();
  try {
    // Validate fresh capacity before creating a durable run.
    if (policy.workspace_limit_mb != null) await api.request("/system/resources/validate", { method: "POST", body: policy, signal });
    const run = await api.create(request, signal);
    remember(run);
    // Preserve the ID before dispatch so a failed start never creates a duplicate run.
    busy = false;
    await openRun(run.id, { requirements: values.code_requirements || "", refresh: false, policy });
    state.run = run;
    busy = true;
    await api.start(run.id, values.code_requirements, controller.signal, policy);
  } catch (error) { handleError(error); }
  finally {
    busy = false;
    updateBusy();
    if (state) await refreshRun();
  }
});

$("confirm-selection").addEventListener("click", () => mutate(async () => {
  await api.select(state.id, [...selected], $("selection-requirements").value.trim(), controller.signal);
}));

$("papers-list").addEventListener("change", (event) => {
  const input = event.target.closest("[data-paper]");
  if (!input) return;
  const id = parseRunId(input.dataset.paper);
  if (input.checked) selected.add(id); else selected.delete(id);
  updateSelection();
});

$("run-controls").addEventListener("click", (event) => {
  const action = event.target.closest("[data-action]")?.dataset.action;
  if (!action) return;
  if (action === "cancel" && !window.confirm("确认取消当前工作流？已保存的论文与执行记录仍会保留。")) return;
  mutate(async () => {
    const signal = controller.signal;
    if (action === "start") await api.start(state.id, state.requirements, signal, state.policy || { mode: "static" });
    if (action === "enter-selection") await api.request(runPath(state.workflow ? "/workflow/literature/resume" : "/selection/start"), {
      method: "POST", signal, body: state.workflow ? undefined : { code_requirements: state.requirements || null, validation_policy: state.policy || { mode: "static" } },
    });
    if (action === "resume") await api.request(workflowPath("/resume"), { method: "POST", body: {}, signal });
    if (action === "cancel") await api.request(workflowPath("/cancel"), { method: "POST", signal });
  });
});

$("refresh-run").addEventListener("click", () => { showNotice(""); refreshRun(); checkHealth(); });
$("show-warnings").addEventListener("click", () => {
  $("warnings-panel").open = true;
  $("warnings-panel").scrollIntoView({ block: "nearest" });
});
$("new-task").addEventListener("click", showCreate);
$("history-list").addEventListener("click", (event) => {
  const removed = event.target.closest("[data-remove-history]")?.dataset.removeHistory;
  if (removed) { deleteTasks([parseRunId(removed)]).catch(handleError); return; }
  const id = event.target.closest("[data-run]")?.dataset.run;
  if (id && !busy) openRun(id).catch(handleError);
});
$("clear-history").addEventListener("click", () => {
  deleteTasks(history.map((item) => item.id)).catch(handleError);
});
$("delete-run").addEventListener("click", () => { if (state) deleteTasks([state.id]).catch(handleError); });
for (const id of ["open-run", "open-run-mobile"]) $(id).addEventListener("click", () => { setSidebar(false); $("open-dialog").showModal(); });
$("open-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (busy) return;
  $("open-dialog").close();
  openRun($("run-id-input").value).catch(handleError);
});
$("connection-settings").addEventListener("click", () => { setSidebar(false); $("settings-dialog").showModal(); });
$("menu-toggle").addEventListener("click", () => setSidebar(!document.body.classList.contains("sidebar-open")));
$("sidebar-backdrop").addEventListener("click", () => { setSidebar(false); $("menu-toggle").focus(); });
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && document.body.classList.contains("sidebar-open")) { setSidebar(false); $("menu-toggle").focus(); } });
$("sidebar").addEventListener("keydown", (event) => {
  if (event.key !== "Tab" || !document.body.classList.contains("sidebar-open")) return;
  const items = [...$("sidebar").querySelectorAll("a[href], button:not(:disabled)")];
  const [first, last] = [items[0], items.at(-1)];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});
document.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
$("settings-form").addEventListener("submit", (event) => {
  event.preventDefault();
  api.token = $("api-token").value.trim();
  $("api-token").value = "";
  $("settings-dialog").close();
  showNotice("连接设置已更新。Token 仅用于当前页面的 API 请求。", "success");
  checkHealth();
  detectResources();
  if (state) refreshRun();
});
$("detect-resources").addEventListener("click", detectResources);
$("retry-resources").addEventListener("click", detectResources);
$("retry-connection").addEventListener("click", checkHealth);
$("resource-options").addEventListener("input", () => { resourceBudgetEdited = true; });
$("resource-options").addEventListener("change", () => { resourceBudgetEdited = true; });
$("execution-mode").addEventListener("change", updateResourceMode);
$("memory-limit").addEventListener("input", updateResourceMode);
for (const id of ["cpu-limit", "workspace-limit"]) $(id).addEventListener("input", updateBudgetSummary);
$("search-form").addEventListener("invalid", (event) => {
  validateSearchFields();
  let details = event.target.closest("details");
  while (details) {
    details.open = true;
    details = details.parentElement.closest("details");
  }
}, true);
function validateSearchFields() {
  const topicError = $("topic").value.trim() ? "" : "请填写研究主题。";
  const dateError = !$("start-date").value || !$("end-date").value ? "请选择完整的论文发表时间范围。"
    : $("start-date").value > $("end-date").value ? "开始日期不能晚于结束日期。" : "";
  for (const [id, message] of [["topic", topicError], ["end-date", dateError]]) {
    $(id).setCustomValidity(message);
    $(id).setAttribute("aria-invalid", String(Boolean(message)));
  }
  $("topic-error").textContent = topicError;
  $("topic-error").hidden = !topicError;
  $("date-error").textContent = dateError;
  $("date-error").hidden = !dateError;
  return !topicError && !dateError;
}
for (const id of ["topic", "start-date", "end-date"]) $(id).addEventListener("input", validateSearchFields);
document.querySelectorAll("[data-topic]").forEach((button) => button.addEventListener("click", () => {
  $("topic").value = button.dataset.topic;
  $("keywords").value = button.dataset.keywords;
  $("description").value = "";
  validateSearchFields();
  $("topic").focus();
}));
$("mnist-example").addEventListener("click", () => {
  $("topic").value = "手写数字识别（MNIST）";
  $("description").value = "寻找适合单机验证的手写数字识别方法，优先选择公开代码、明确训练与测试划分、报告分类准确率的轻量模型。";
  $("keywords").value = "handwritten digit recognition, MNIST, convolutional neural network";
  $("start-date").value = "1990-01-01";
  validateSearchFields();
  $("topic").focus();
});
$("m5-example").addEventListener("click", () => {
  $("topic").value = "An Ensemble of Simple Convolutional Neural Network Models for MNIST Digit Recognition";
  $("description").value = "检索 arXiv:2008.10400 的作者论文，后续只做 M5 单模型、固定种子、2 轮 MNIST 试跑，不进行论文完整集成实验。";
  $("keywords").value = "MNIST, simple convolutional neural network";
  $("start-date").value = "2020-01-01";
  $("end-date").value = "2021-12-31";
  $("max-results").value = "3";
  validateSearchFields();
  $("topic").focus();
});
$("ranking-system").addEventListener("change", (event) => {
  const system = event.target.value;
  $("quality-levels").hidden = !system;
  $("allowed-levels").required = Boolean(system);
  $("allowed-levels").placeholder = system === "core" ? "A*, A, B" : "A, B";
  $("levels-hint").textContent = `允许等级：${system === "core" ? "A*、A、B、C" : "A、B、C"}，用逗号分隔。评级筛选依赖已导入的会议期刊目录。`;
});
$("export-run").addEventListener("click", () => {
  if (!state?.run) return;
  const record = {
    exported_at: new Date().toISOString(),
    note: "工作流完成不代表论文实验指标已复现；请按验证报告核对执行范围。",
    literature: state.run, workflow: state.workflow, papers: state.papers,
    node_executions: state.nodes, result: state.result, resource_policy: state.policy,
  };
  const url = URL.createObjectURL(new Blob([JSON.stringify(record, null, 2)], { type: "application/json" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `module-agent-run-${state.id}.json`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

async function initialize() {
  $("style-alert").hidden = getComputedStyle(document.documentElement).getPropertyValue("--workbench-ui-ready").trim() === "1";
  const today = new Date();
  const localDate = (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  $("end-date").value = localDate(today);
  $("start-date").value = `${today.getFullYear() - 3}-01-01`;
  renderHistory();
  try {
    const config = await fetch("/ui/config", { signal: AbortSignal.timeout(5000), cache: "no-store" });
    if (!config.ok) throw new Error("无法读取工作台 API 配置。");
    api.prefix = (await config.json()).api_prefix.replace(/\/$/, "");
  } catch (error) { handleError(error); }
  checkHealth();
  detectResources();
  const id = new URLSearchParams(location.hash.slice(1)).get("run");
  // Restoring a URL must not undo a user's removal from recent history.
  if (id) await openRun(id, { rememberHistory: false }).catch(handleError);
}

const elapsedTimer = setInterval(() => { if (state && !$("run-view").hidden) updateElapsed(); }, 1000);
$("retry-styles").addEventListener("click", () => window.location.reload());
window.addEventListener("pagehide", () => { clearTimeout(pollTimer); clearInterval(elapsedTimer); controller.abort(); resourceController?.abort(); });
initialize();
