import { escapeHtml as e } from "./core.mjs";

const ACTIVE = new Set(["queued", "preparing", "running", "cancelling"]);
const STATUS = { draft: "等待确认", queued: "排队中", preparing: "准备环境与数据", running: "正在执行", cancelling: "正在停止", cancelled: "已停止", interrupted: "Worker 失联", failed: "失败", timed_out: "已超时", completed: "试跑完成" };
const STAGE = { awaiting_approval: "等待确认预算", queued: "等待执行机", preparing: "下载并校验源码、MNIST，准备镜像", environment: "验证环境与 GPU 内核", train: "训练 M5 · 共 2 轮", evaluate: "独立评估 10,000 张测试图片", collecting: "收集与交叉校验指标", finished: "结果已保存" };

export function experimentSummary(job) {
  const m = job.result?.metrics;
  return m ? `测试准确率 ${m.accuracy_percent.toFixed(2)}% · 正确 ${m.correct} / ${m.evaluated_samples} · 错误 ${m.wrong} · 已训练 ${m.completed_epochs} 轮` : "";
}

export class ExperimentPanel {
  constructor(element, api, notify) {
    this.element = element;
    this.api = api;
    this.notify = notify;
    this.runId = null;
    this.generation = 0;
    this.busy = false;
    element.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-experiment]");
      if (button) this.action(button);
    });
  }

  close() {
    clearTimeout(this.timer);
    this.generation++;
    this.runId = null;
    this.element.hidden = true;
  }

  open(id, status) {
    if (status !== "completed") { this.close(); return; }
    if (this.runId === id) return;
    this.close();
    this.runId = id;
    this.element.hidden = false;
    this.element.innerHTML = '<h2>真实实验</h2><p role="status">正在读取实验状态…</p>';
    this.refresh();
  }

  async refresh() {
    clearTimeout(this.timer);
    const generation = this.generation;
    try {
      const data = await this.api.request(`/workflow/runs/${this.runId}/experiments`);
      if (generation !== this.generation) return;
      this.data = data;
      this.render();
      if (data.jobs.some((j) => ACTIVE.has(j.status))) this.timer = setTimeout(() => this.refresh(), 2500);
    } catch (error) {
      if (generation !== this.generation) return;
      this.element.innerHTML = `<h2>真实实验</h2><p role="alert">${e(error.message)}</p><button class="button" data-experiment="refresh">重试</button>`;
      this.timer = setTimeout(() => this.refresh(), 10000);
    }
  }

  render() {
    // Preserve unsaved budgets and checkboxes during progress polling.
    const saved = new Map([...this.element.querySelectorAll("input,select")].map((el) => [el.id, el.type === "checkbox" ? el.checked : el.value]));
    const expanded = new Map([...this.element.querySelectorAll("details[data-experiment-key]")].map((el) => [el.dataset.experimentKey, el.open]));
    const { eligible_papers: papers, workers, jobs, notice } = this.data;
    const devices = workers.flatMap((w) => (w.resources.sandbox_ready ? w.resources.gpus : []).map((g) => ({ worker: w, gpu: g })));
    const active = jobs.some((j) => ACTIVE.has(j.status));
    this.element.innerHTML = `<div class="panel-heading"><h2>真实实验 <span class="tiny-count">M5 / MNIST</span></h2><button class="button" data-experiment="refresh">检测执行机</button></div>
      <p class="muted">${e(notice)} 静态流程与真实实验分别记录。</p>
      <p class="field-hint">本实验使用已审核的固定作者代码配方，不沿用上方自动发现的代码产物；上方代码获取或静态检查失败，不等于此实验失败，反之亦然。</p>
      ${papers.length ? `<details class="options" data-experiment-key="create" ${jobs.length ? "" : "open"}><summary><span>创建试跑计划</span><span class="disclosure-arrow" aria-hidden="true"></span></summary><div class="details-body">
        ${devices.length ? `<div class="experiment-grid"><label>论文<select id="experiment-paper">${papers.map((p) => `<option value="${p.id}">${e(p.title)}</option>`).join("")}</select></label>
        <label>执行机 GPU<select id="experiment-device">${devices.map((d, i) => `<option value="${i}">${e(d.gpu.name)} · 剩余 ${e(d.gpu.memory_free_mb ?? "未知")} MB 显存</option>`).join("")}</select></label>
        <label>CPU 核数<input id="experiment-cpu" type="number" min="1" max="8" step="1" value="2" required></label>
        <label>内存（MB）<input id="experiment-memory" type="number" min="2048" max="16384" step="256" value="4096" required></label>
        <label>输出预算（MB，监测式）<input id="experiment-output" type="number" min="64" max="4096" value="2048" required></label>
        <label>训练与评估限时（秒）<input id="experiment-timeout" type="number" min="60" max="900" value="900" required></label></div>
        <p class="field-hint">CPU、内存限额用于执行容器；准备阶段另限 20 分钟，首次镜像缓存约需 16 GB（不计入输出预算）。输出空间为监测式预算，显存无硬限额。资源检测不是预留。</p>
        <button class="button primary" data-experiment="propose" ${active ? "disabled" : ""}>生成计划，不执行代码</button>` : `<p role="status">未发现可用的 GPU 实验 Worker，不能开始训练。论文检索和静态检查不受影响。</p><p class="field-hint">在 GPU / Docker 执行机终端运行：<code>uv run python -m module_agent.cli.run_experiment_worker</code>，然后点击“检测执行机”。</p>`}
      </div></details>` : '<p class="field-hint">当前已选论文没有已审核的真实实验配方，不会套用其他论文的训练结果。</p>'}
      <div class="experiment-jobs">${jobs.map((job) => this.jobHtml(job)).join("")}</div>`;
    this.devices = devices;
    this.element.querySelectorAll("details[data-experiment-key]").forEach((el) => {
      if (expanded.has(el.dataset.experimentKey)) el.open = expanded.get(el.dataset.experimentKey);
    });
    for (const [id, value] of saved) {
      const el = this.element.querySelector(`#${id}`);
      if (el) { if (el.type === "checkbox") el.checked = value; else el.value = value; }
    }
    this.element.querySelectorAll("button").forEach((b) => { b.disabled ||= this.busy; });
  }

  jobHtml(job) {
    const p = job.proposal, b = p.budget;
    const id = job.id;
    return `<article class="experiment-job" data-experiment-job="${id}"><div class="panel-heading"><h3>M5 两轮试跑</h3><span class="badge">${e(STATUS[job.status] || job.status)}</span></div>
      <p>${e(STAGE[job.stage] || STATUS[job.status] || job.stage)}</p>
      ${ACTIVE.has(job.status) ? '<progress class="experiment-progress" aria-label="实验进行中，按实际阶段显示"></progress>' : ""}
      <p class="field-hint">CPU ≤ ${e(b.cpu_limit)} 核 · 内存 ≤ ${e(b.memory_mb)} MB · 输出预算 ${e(b.output_mb)} MB（监测） · 执行限时 ${e(b.timeout_seconds)} 秒<br>固定种子 0 · 60,000 张训练图片 · 10,000 张测试图片 · ${e(p.epochs)} 轮</p>
      ${job.status === "draft" ? `<p>${e(p.notice)}</p><div class="experiment-consent">
        <label><input id="agree-code-${id}" type="checkbox">我同意执行固定作者代码，并允许准备阶段联网下载。</label>
        <label><input id="agree-license-${id}" type="checkbox">我已自行确认源码使用权限（未发现许可证，勾选不代表获得授权）。</label>
        <label><input id="agree-gpu-${id}" type="checkbox">我知道 GPU 显存没有硬限额，可能影响同机任务。</label></div>
        <div class="run-controls"><button class="button primary" data-experiment="confirm" data-id="${id}">确认预算并开始试跑</button><button class="button" data-experiment="cancel" data-id="${id}">放弃计划</button></div>` : ""}
      ${ACTIVE.has(job.status) ? `<button class="button danger-button" data-experiment="cancel" data-id="${id}" ${job.status === "cancelling" ? "disabled" : ""}>停止实验</button>` : ""}
      ${job.error ? `<p class="experiment-error" role="alert">${e(job.error)}</p>` : ""}
      ${job.result?.metrics ? `<p class="experiment-metric">${e(experimentSummary(job))}</p><p class="muted">仅验证短程训练与评估链路；没有完成论文的 30 次 × 150 轮实验，不可与论文指标直接比较。</p>` : ""}
      ${job.log_tail ? `<details class="options" data-experiment-key="logs-${id}"><summary>执行日志（最近部分，保留原始输出）<span class="disclosure-arrow" aria-hidden="true"></span></summary><pre class="experiment-log">${e(job.log_tail)}</pre></details>` : ""}
      ${(job.artifacts || []).length ? `<div class="experiment-downloads">${job.artifacts.map((name) => `<button class="button" data-experiment="download" data-id="${id}" data-name="${e(name)}">下载 ${e(({ "weights.pth": "模型权重", "metrics.json": "指标", "environment.json": "环境记录", "execution.log": "日志", "training.csv": "训练记录", "training-log.txt": "训练记录", "wrong-indices.txt": "错误样本编号", "plan.json": "执行计划", "consent.json": "执行授权", "result.json": "结果" })[name] || name)}</button>`).join("")}</div>` : ""}
      <p class="field-hint">实验 ${e(id)} · ${e(new Date(job.created_at).toLocaleString("zh-CN"))}</p></article>`;
  }

  async action(button) {
    if (this.busy) return;
    const action = button.dataset.experiment, id = button.dataset.id;
    if (action === "refresh") { await this.refresh(); return; }
    const generation = this.generation, runId = this.runId;
    this.notify("");
    this.busy = true;
    button.disabled = true;
    const originalLabel = button.textContent;
    button.textContent = "正在处理…";
    try {
      if (action === "propose") {
        const inputs = [...this.element.querySelectorAll("input[type=number]")];
        if (inputs.some((el) => !el.reportValidity())) return;
        const device = this.devices[Number(this.element.querySelector("#experiment-device").value)];
        await this.api.request(`/workflow/runs/${runId}/experiments`, { method: "POST", body: {
          paper_id: Number(this.element.querySelector("#experiment-paper").value), worker_id: device.worker.id,
          budget: { gpu_uuid: device.gpu.uuid, cpu_limit: Number(this.element.querySelector("#experiment-cpu").value), memory_mb: Number(this.element.querySelector("#experiment-memory").value), output_mb: Number(this.element.querySelector("#experiment-output").value), timeout_seconds: Number(this.element.querySelector("#experiment-timeout").value), temporary_mb: 512 },
        } });
        this.element.querySelector('[data-experiment-key="create"]').open = false;
      } else if (action === "confirm") {
        if (!["code", "license", "gpu"].every((name) => this.element.querySelector(`#agree-${name}-${id}`).checked)) throw new Error("请阅读实验范围，并逐项确认执行、源码权限与 GPU 风险。");
        const job = this.data.jobs.find((j) => j.id === id);
        await this.api.request(`/experiments/${id}/confirm`, { method: "POST", body: { proposal_sha256: job.proposal_sha256, execute_code: true, allow_preparation_network: true, acknowledge_source_license: true, acknowledge_gpu_not_memory_capped: true } });
      } else if (action === "cancel") {
        await this.api.request(`/experiments/${id}/cancel`, { method: "POST" });
      } else if (action === "download") {
        const name = button.dataset.name;
        const response = await this.api.fetcher(`${this.api.prefix}/experiments/${id}/artifacts/${encodeURIComponent(name)}`, { headers: this.api.token ? { Authorization: `Bearer ${this.api.token}` } : {}, signal: AbortSignal.timeout(45000), cache: "no-store" });
        if (!response.ok) throw new Error(`产物下载失败（HTTP ${response.status}）`);
        const url = URL.createObjectURL(await response.blob());
        const a = document.createElement("a"); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (error) { if (generation === this.generation) this.notify(error.message); }
    finally {
      this.busy = false;
      if (generation === this.generation) {
        button.textContent = originalLabel;
        await this.refresh();
        if (action === "propose") this.element.querySelector(".experiment-job")?.scrollIntoView({ block: "center" });
      }
    }
  }
}
