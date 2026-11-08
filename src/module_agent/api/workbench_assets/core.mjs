/** Data conversion shared by the workbench and its contract tests. */
export function splitTerms(value = "") {
  return [...new Set(String(value).split(/[,，;；\n]+/).map((part) => part.trim()).filter(Boolean))];
}

export function parseRunId(value) {
  const text = String(value ?? "");
  if (!/^[1-9]\d*$/.test(text) || !Number.isSafeInteger(Number(text))) {
    throw new Error("请输入正整数任务 ID。");
  }
  return Number(text);
}

export function buildSearchRequest(values) {
  const topic = String(values.topic || "").trim();
  if (!topic) throw new Error("请填写研究方向。");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(values.start_date || "") ||
      !/^\d{4}-\d{2}-\d{2}$/.test(values.end_date || "")) {
    throw new Error("请选择完整的检索时间范围。");
  }
  if (values.start_date > values.end_date) throw new Error("开始日期不能晚于结束日期。");
  const maxResults = Number(values.max_results);
  if (!Number.isInteger(maxResults) || maxResults < 1 || maxResults > 20) {
    throw new Error("工作台每次支持检索 1～20 篇论文。");
  }
  const keywords = splitTerms(values.keywords);
  const ranking = values.ranking_system || "";
  if (ranking && !["ccf", "core"].includes(ranking)) throw new Error("不支持的评级体系。");
  const levels = splitTerms(values.allowed_levels);
  const validLevels = ranking === "core" ? ["A*", "A", "B", "C"] : ["A", "B", "C"];
  if (ranking && (!levels.length || levels.some((level) => !validLevels.includes(level)))) {
    throw new Error("请选择对应评级体系中的有效等级。");
  }
  return {
    topic,
    description: String(values.description || "").trim() || topic,
    start_date: values.start_date,
    end_date: values.end_date,
    keywords: keywords.length ? keywords : [topic],
    exclusion_keywords: splitTerms(values.exclusion_keywords),
    venues: splitTerms(values.venues),
    venue_quality: ranking ? { ranking_system: ranking, allowed_levels: levels } : null,
    max_results: maxResults,
  };
}

export function safeUrl(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

export function paperIntegrityDisplay(paper) {
  const value = paper?.integrity;
  if (value?.status === "retracted") return { label: "已发现撤稿", tone: "red", blocked: true, note: "不能用于本次代码任务。" };
  if (value?.status === "notice") return { label: "撤稿声明", tone: "red", blocked: true, note: "这是撤稿声明，不是待复现的方法论文。" };
  if (value?.status === "not_flagged" && !value.warnings?.length) return { label: "未发现撤稿标记", tone: "gray", blocked: false, note: "仅反映已核对的元数据，不代表论文质量或指标有效性保证。" };
  return { label: value?.warnings?.length ? "核验不完整" : "撤稿状态未核验", tone: "amber", blocked: false, note: "未完整核验撤稿信息；不能据此认定没有撤稿。" };
}

export function repositoryOriginNote(artifact) {
  const types = new Set((artifact?.evidence || []).map((item) => item.evidence_type));
  if (artifact?.origin === "official" && !types.has("implementation_url")) {
    return { label: "历史来源判定待复核", note: "旧版本可能仅因论文页面出现链接就标为官方；此处不沿用该结论，原始记录仍保留。" };
  }
  if (["unknown", "third_party"].includes(artifact?.origin) && types.has("implementation_claim") && !types.has("implementation_url")) {
    return { label: "仓库实现声明（来源待核验）", note: "README 声称实现该论文，但没有足够证据确认作者或官方身份，也不能据此断言它是第三方。" };
  }
  return null;
}

export function buildResourcePolicy(values, snapshot) {
  if (!snapshot) throw new Error("自定义资源预算或沙箱验证需要先成功检测运行环境。");
  const cpu = Number(values.cpu_limit);
  const memory = Number(values.memory_limit_mb);
  const workspace = Number(values.workspace_limit_mb);
  const temporary = Number(values.temporary_storage_mb);
  const timeout = Number(values.timeout_seconds);
  if (!Number.isFinite(cpu) || cpu < 0.1 || cpu > Math.min(8, snapshot.available_cpu_count)) {
    throw new Error("CPU 上限必须在 0.1 与检测到的可用 CPU（最多 8 核）之间。");
  }
  if (!Number.isInteger(memory) || memory < 128 || memory > 16384 ||
      (snapshot.memory_available_mb != null && memory > snapshot.memory_available_mb)) {
    throw new Error("内存预算应为 128～16384 MiB，且不能超过可用内存。");
  }
  if (!Number.isInteger(workspace) || workspace < 128 || workspace > 65536 ||
      (snapshot.workspace_free_mb != null && workspace > snapshot.workspace_free_mb)) {
    throw new Error("工作区预算应为 128～65536 MiB，且不能超过剩余磁盘空间。");
  }
  if (!Number.isInteger(temporary) || temporary < 16 || temporary > memory) {
    throw new Error("沙箱临时空间应不少于 16 MiB，且不能超过内存预算。");
  }
  if (!Number.isInteger(timeout) || timeout < 1 || timeout > 900) {
    throw new Error("单次沙箱检查限时应在 1～900 秒之间。");
  }
  const mode = values.validation_mode || "static";
  if (!["static", "sandbox"].includes(mode)) throw new Error("不支持的验证模式。");
  if (mode === "sandbox" && !snapshot.sandbox_ready) throw new Error(snapshot.sandbox_reason || "沙箱未就绪。");
  const gpuId = mode === "sandbox" ? values.gpu_device_id || "" : "";
  if (gpuId && !(snapshot.gpus || []).some((device) => device.uuid === gpuId)) {
    throw new Error("所选 GPU 不在当前环境的检测结果中。");
  }
  return {
    mode, cpu_limit: cpu, memory_limit_mb: memory, workspace_limit_mb: workspace,
    temporary_storage_mb: temporary, timeout_seconds: timeout,
    compute_target: gpuId ? "gpu" : "cpu", gpu_device_ids: gpuId ? [gpuId] : [],
    allow_network: false,
  };
}

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

export function evidenceSummary(artifact, report) {
  return {
    repository: Boolean(artifact?.status === "repository_ready" && artifact?.repository_url && artifact?.commit_sha),
    candidate: Boolean(artifact?.implementation_generated),
    staticPassed: Boolean(report?.mode === "static" && report?.status === "passed"),
    codeExecuted: report?.code_executed === true,
    // No backend field currently establishes a comparison with paper metrics.
    metricsReproduced: false,
  };
}

export function formatDuration(milliseconds) {
  if (milliseconds == null || !Number.isFinite(Number(milliseconds))) return "—";
  const seconds = Number(milliseconds) / 1000;
  return seconds < 1 ? `${Math.round(milliseconds)} ms` : seconds < 60
    ? `${seconds.toFixed(1)} s` : `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

/** Stage completion is observable; progress within a model call is not. */
export function workflowProgress({ run, workflow, nodes = [], result, syncError } = {}) {
  const completed = (name) => nodes.some((node) => node.node === name && node.status === "completed");
  const terminal = new Set(["completed", "failed", "cancelled", "timed_out"]);
  const status = workflow?.status;
  const codeDone = completed("code_wait") || completed("validation") || Boolean(result?.code_artifacts?.length);
  const selectionDone = completed("paper_selection") || status === "waiting_for_code" || status === "completed" || codeDone;
  const done = [run?.status === "completed", selectionDone, codeDone, completed("validation") || Boolean(result?.validation_reports?.length)];
  if (status === "completed") done.fill(true);
  const progress = {
    phase: "working", stage: 0, title: "正在读取任务", detail: "请稍候。",
    done, completedStages: done.filter(Boolean).length,
    startedAt: workflow?.created_at || run?.started_at || run?.created_at || null,
    finishedAt: workflow?.finished_at || (["failed", "cancelled"].includes(run?.status) ? run?.completed_at : null),
  };
  if (syncError) return { ...progress, phase: "unavailable", title: syncError.status === 401 ? "需要连接认证" : syncError.status === 404 ? "未找到任务" : "暂时无法同步进度", detail: "查看上方提示，连接恢复后会继续更新。" };
  if (!run) return progress;
  if (status === "completed") return { ...progress, phase: "complete", stage: 3, title: "流程已完成", detail: result ? "结果已保存，可以查看或导出。" : "正在读取结果，暂未返回时可点击刷新。" };
  if (terminal.has(status) || ["failed", "cancelled"].includes(run.status)) {
    const stopped = terminal.has(status) ? status : run.status;
    return { ...progress, phase: stopped, stage: Math.min(progress.completedStages, 3), title: { failed: "任务失败", cancelled: "任务已取消", timed_out: "任务已超时" }[stopped], detail: workflow?.error || run.error || "已停止处理，可在运行记录中查看原因。" };
  }
  if (status === "waiting_for_selection") return { ...progress, phase: "waiting", stage: 1, title: "请选择论文", detail: "检索已完成。勾选论文后确认继续；等待确认不计入执行超时。" };
  if (status === "waiting_for_code" || (selectionDone && !codeDone)) return { ...progress, stage: 2, title: "正在处理代码", detail: "这一步会查找并获取仓库，或生成候选实现。完成后进入验证。" };
  if (codeDone && !done[3]) return { ...progress, stage: 3, title: "正在验证代码", detail: "正在检查产物并生成验证报告。" };
  if (run.status === "completed") return { ...progress, phase: "waiting", stage: 1, title: "文献检索已完成", detail: "正在衔接论文选择；也可以点击下方的“进入论文选择”。" };
  if (!workflow && run.status === "pending") return { ...progress, phase: "idle", title: "任务尚未启动", detail: "任务已保存，点击下方按钮继续。" };
  if (run.status === "queued" || (run.status === "pending" && workflow)) return { ...progress, phase: "queued", title: "等待文献检索", detail: "任务已提交，正在等待检索服务处理。" };
  return { ...progress, title: "正在检索文献", detail: "正在检索并筛选论文，完成后会提示你选择。" };
}

export function elapsedTime(startedAt, finishedAt, now = Date.now()) {
  const start = Date.parse(startedAt);
  const end = finishedAt ? Date.parse(finishedAt) : now;
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "—";
  const total = Math.max(0, Math.floor((end - start) / 1000));
  const days = Math.floor(total / 86400);
  const hours = Math.floor(total / 3600) % 24;
  const minutes = Math.floor(total / 60) % 60;
  const seconds = total % 60;
  return `${days ? `${days}天 ` : ""}${hours || days ? `${String(hours).padStart(2, "0")}:` : ""}${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export class ApiError extends Error {
  constructor(message, status, retryAfter = 0) {
    super(message);
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

export class WorkbenchApi {
  constructor(prefix = "/api", fetcher = globalThis.fetch.bind(globalThis)) {
    this.prefix = prefix.replace(/\/$/, "");
    this.fetcher = fetcher;
    this.token = "";
  }

  async request(path, { method = "GET", body, signal, optional = false } = {}) {
    const headers = { Accept: "application/json" };
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const timeout = AbortSignal.timeout(45000);
    const response = await this.fetcher(`${this.prefix}${path}`, {
      method, headers, signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
    if (optional && response.status === 404) return null;
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = payload?.detail ?? payload?.message;
      const message = typeof detail === "string" ? detail : Array.isArray(detail)
        ? detail.map((item) => `${(item.loc || []).join(".")}: ${item.msg}`).join("；")
        : `请求失败（HTTP ${response.status}）`;
      throw new ApiError(message, response.status, Number(response.headers?.get("Retry-After")) || 0);
    }
    return payload;
  }

  create(request, signal) { return this.request("/literature/runs", { method: "POST", body: request, signal }); }
  remove(id, signal) { return this.request(`/literature/runs/${parseRunId(id)}`, { method: "DELETE", signal }); }
  start(id, requirements, signal, policy = { mode: "static" }) {
    return this.request(`/literature/runs/${parseRunId(id)}/workflow/start`, {
      method: "POST", signal,
      body: { code_requirements: requirements || null, validation_policy: policy },
    });
  }
  select(id, ids, requirements, signal) {
    if (!ids.length || ids.length > 20) throw new Error("请选择 1～20 篇论文。");
    return this.request(`/literature/runs/${parseRunId(id)}/selection`, {
      method: "POST", signal,
      body: { selected_paper_ids: ids.map(parseRunId), code_requirements: requirements || null },
    });
  }
}
