# M8 生产就绪说明

M8 的目标是让已经串通的多 Agent MVP 具备可恢复、可查询、可追踪和
可安全部署的基本工程边界。本阶段不运行论文实验，也不扩大 Agent 的研究能力。

## 已交付

- `CodeRun`、`ValidationRun`、`ModuleWorkflowRun` PostgreSQL 生命周期。
- 每个 attempt 的幂等执行；运行中、完成和失败状态使用独立短事务保存。
- 工作流 deadline、超时失败和协作式取消。
- 人工等待点超时后可显式续期，并保留原 trace 和 LangGraph checkpoint。
- request ID、trace ID、workflow ID、agent run ID、message ID 关联日志。
- 每个 LangGraph 节点的状态、耗时和脱敏输入/输出摘要。
- Workflow 成功率、平均耗时和节点失败统计接口。
- 生产 Bearer 鉴权、安全配置启动检查、非 root 与只读应用容器。
- GitHub Actions 中的测试、Alembic、LangGraph 初始化和镜像构建。
- 不调用外部论文实验的确定性端到端测试。
- 独立 CPU/GPU Code Worker 队列；API 只投递任务，LangGraph 在 checkpoint
  等待完成事件后恢复。
- `/metrics`、RabbitMQ Prometheus exporter、Prometheus 与自动配置的 Grafana
  dashboard；包含 HTTP、队列结果、队列积压、LLM 耗时及 token。
- 显式启用的依赖安装和完整 pytest 验证。安装与执行只发生在只读挂载、限额的
  Docker 沙箱中，默认仍为 static，不执行第三方代码。
- 无可信仓库时可生成受限的候选算法源码和测试；产物明确标记为未验证，并由
  Validation Agent 决定是否在沙箱运行。
- 工作区两阶段清理：先移动到 `.trash`，超过第二个保留期才永久清除。
- `alembic check` 排除 LangGraph 自管表，并消除重复唯一约束造成的 schema 漂移。

## 查询接口

- `GET /api/workflow/runs/{run_id}`：工作流生命周期和 trace。
- `POST /api/workflow/runs/{run_id}/cancel`：请求取消。
- `POST /api/workflow/runs/{run_id}/resume`：续期已超时且仍停在人工等待点的工作流；请求体可传 `timeout_seconds`。
- `GET /api/workflow/runs/{run_id}/nodes`：节点执行轨迹。
- `GET /api/workflow/metrics`：成功率和耗时汇总。
- `GET /api/code/runs/{run_id}/executions`：CodeRun 列表。
- `GET /api/validation/runs/{run_id}/executions`：ValidationRun 列表。

生产环境除健康检查外需发送：

```text
Authorization: Bearer <API_AUTH_TOKEN>
```

`API_AUTH_TOKEN` 在生产环境至少 32 字符。生产启动还会拒绝默认开发密码、
相对工作区、缺失的外部服务 URL、未配置的 Qwen/Jev 密钥和 `:latest`
沙箱镜像。

## 取消语义

取消是协作式的：尚未开始的后续节点不会再运行；已经进入 Git、LLM 或沙箱的
单次调用会先到达其自身超时/退出边界，然后工作流停止。这样不会通过强杀进程
破坏数据库事务或留下不可控的子进程。

## 超时续期语义

超时续期不是任意失败重试。只有状态为 `timed_out`，并且 LangGraph checkpoint
仍停在 Literature 完成等待或论文人工选择等待点时才能续期。续期会清除原超时错误、
生成新 deadline，并保留原 trace、已有论文结果和节点轨迹；已经进入 Code 或
Validation 的超时任务不能通过该接口恢复。

示例：

```json
POST /api/workflow/runs/20/resume
{"timeout_seconds": 1800}
```

## 真实安全验收基线

2026-09-27 使用真实 HTTP API、PostgreSQL、RabbitMQ、Redis、OpenAlex、
Semantic Scholar 和 Qwen 完成了 run `20` 的完整验收：

- Literature、Code、Validation 均在第一次 attempt 完成，总工作流状态为
  `completed`，并共享同一个 trace ID。
- Semantic Scholar 三次查询全部成功；OpenAlex 首次成功，后两次收到 429，
  工作流按来源降级策略继续完成。
- 用户选择原始 Transformer 论文后，由于元数据没有论文明确链接的可信仓库，
  Code Agent 安全降级为复现计划，没有安装依赖或执行论文代码。
- Validation Agent 使用 `static` 模式检查复现计划，结果为 `partial`，明确保留
  待补充的超参数和数据处理问题。
- 人工选择等待超过 deadline 后，通过显式续期接口恢复同一 checkpoint 和
  trace，随后完成下游流程。
- 2026-09-28 补齐独立 Code Worker、候选实现生成、安全项目测试、工作区清理
  和 Prometheus/Grafana 后，全量自动化回归结果为 `1010 passed, 2 skipped`。

## 运行新组件

- 默认启动 CPU Code Worker、Code completion worker、Prometheus 和 Grafana：
  `docker compose up -d --build`。
- 有 NVIDIA Container Toolkit 的节点可额外启动 GPU 队列：
  `docker compose --profile gpu up -d code-gpu-worker`。
- 工作区清理先执行 dry-run：
  `uv run python -m module_agent.cli.cleanup_code_workspaces`。
- 确认结果后执行两阶段清理：
  `docker compose --profile maintenance run --rm workspace-cleaner`。
- Prometheus 默认位于 `http://localhost:9090`，Grafana 默认位于
  `http://localhost:3000`。

## 明确延期

- 多租户用户身份、任务归属和行级数据隔离。
- PDF 与大型模型权重的长期对象存储归档。当前 PDF 仅受限下载并在内存解析，
  项目不自动下载模型权重，因此该延期项不影响现有工作流。
