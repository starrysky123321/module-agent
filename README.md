# Module Agent

一个面向计算机领域论文检索、代码获取或复现、隔离验证的多 Agent 工作流。
系统使用 LangGraph 协调 Literature Agent、Code Agent、Validation Agent 和
Supervisor Agent，并在论文选择阶段保留人工确认入口。

## 当前能力

- 根据主题、时间、关键词、会议期刊与 CCF/ICORE 等级检索论文。
- 聚合 OpenAlex 与 Semantic Scholar，统一元数据、去重、筛选和持久化。
- 从 GitHub、论文 PDF、论文页面和补充材料发现代码仓库。
- 无可信仓库时生成明确标记的候选复现实现。
- 在默认静态、显式沙箱的安全策略下验证代码产物。
- 通过 PostgreSQL、Redis、RabbitMQ 和 LangGraph checkpoint 支持异步执行、
  暂停、恢复、重试、死信恢复与追踪。
- 提供 Prometheus 指标和 Grafana dashboard。
- 提供依赖就绪探针、Redis API 限流、审计日志、告警规则和安全运维演练工具。

当前版本是单用户 MVP；多租户身份、任务归属和行级隔离尚未实现。

## 快速启动

需要安装 Docker、Docker Compose 和 [uv](https://docs.astral.sh/uv/)。

```bash
cp .env.example .env
uv sync
docker compose up -d --build
```

服务启动后：

- API：<http://localhost:8000>
- OpenAPI：<http://localhost:8000/docs>
- Prometheus：<http://localhost:9090>
- Grafana：<http://localhost:3000>
- RabbitMQ 管理页：<http://localhost:15672>
- Alertmanager：<http://localhost:9093>

外部模型或数据源需要在本地 `.env` 中填写对应密钥；`.env` 不会提交到 Git。
Compose 暴露的开发端口默认只绑定到 `127.0.0.1`。

## 验证

```bash
uv run pytest -q
uv run pytest -q --cov=module_agent --cov-fail-under=80
uv run ruff check src tests
uv run basedpyright src --level error
uv run alembic check
docker compose config --quiet
```

## 生产运行与演练

存活探针 `/api/health/` 只判断 API 进程是否存活；就绪探针
`/api/health/ready` 会并行检查 PostgreSQL、Redis 和 RabbitMQ。Compose
使用就绪探针判断 API 容器是否能接收真实任务。

生产环境必须配置长度至少 32 位的 `API_AUTH_TOKEN`，并设置：

```dotenv
APP_ENV=production
API_RATE_LIMIT_ENABLED=true
API_RATE_LIMIT_FAIL_OPEN=false
API_RATE_LIMIT_REQUESTS=120
API_RATE_LIMIT_WINDOW_SECONDS=60
```

敏感值也可以通过 `*_FILE` 从只读秘密文件加载。例如，将本地秘密目录挂载到
容器的 `/run/secrets` 后，设置
`API_AUTH_TOKEN_FILE=/run/secrets/api_auth_token`。数据库、Redis、RabbitMQ、
LangGraph、Qwen、GitHub、Semantic Scholar、OpenAlex 和 Typesafe 的对应配置
同样支持 `_FILE` 后缀。不要同时设置同一个秘密的直接值和文件值。

小规模压力测试和长时间连续运行使用同一个只读 GET 工具：

```bash
# 1000 次请求，20 并发
uv run python -m module_agent.cli.run_api_load_test \
  --requests 1000 --concurrency 20

# 连续运行 30 分钟；请先在非生产环境确认目标路径
uv run python -m module_agent.cli.run_api_load_test \
  --duration-seconds 1800 --concurrency 10 \
  --path /api/health/ready
```

报告包含吞吐、错误率、p95 和最大耗时；超过阈值时命令返回非零退出码。
发布前可以通过公开 API 跑一次静态验证的完整 Agent 流程：

```bash
uv run python -m module_agent.cli.run_release_acceptance \
  --topic "graph attention networks for node classification" \
  --keyword "graph attention network" \
  --max-results 3 \
  --paper-count 1
```

该命令会自动选择排名靠前的论文，但不会启用依赖安装或项目实验。默认总超时
为 1800 秒，输出包含每个阶段的耗时、Run ID、最终结果或明确的失败阶段。

如需验证容器进程被强制终止后的恢复能力，明确确认后执行：

```bash
scripts/service_recovery_drill.sh api --confirm
```

Compose 启动时，`workspace-init` 会把持久化 Code Workspace volume 修正为应用
用户 `10001:10001` 可写。Completion worker 在 PostgreSQL 连接中断后会重建
LangGraph checkpointer 并重试当前事件，无需人工重启 worker。

Literature/Code completion 死信由 `completion-recovery-worker` 延迟重放；默认每
30 秒重放一次，最多 3 次。超过上限或内容无效的消息不会丢弃，而是保留在
`literature.completed.parked.v1` 或 `code.completed.parked.v1`。可通过以下变量
调整边界：

```dotenv
COMPLETION_DEAD_LETTER_REPLAY_LIMIT=3
COMPLETION_DEAD_LETTER_RETRY_DELAY_MS=30000
```

数据库备份和恢复演练：

```bash
scripts/backup_postgres.sh
scripts/restore_postgres_drill.sh backups/module-agent-YYYYMMDDTHHMMSSZ.dump
```

恢复脚本拒绝覆盖主库，只允许恢复到名称以 `_restore_drill` 结尾的独立数据库。
请定期在隔离环境执行演练并检查业务表、Alembic 版本和关键记录。

Prometheus 默认加载可用性、5xx、p95 延迟、死信队列和通知失败告警。
默认 Alertmanager 只在本机 UI 展示告警。启用外部通知时：

```bash
cp observability/alertmanager.webhook.example.yml \
  observability/alertmanager.local.yml
chmod 600 observability/alertmanager.local.yml
# 编辑本地文件中的通知网关，再在 .env 设置：
# ALERTMANAGER_CONFIG_FILE=./observability/alertmanager.local.yml
docker compose up -d alertmanager prometheus
```

`alertmanager.local.yml` 已被 Git 忽略，通知凭据不会进入仓库。

GPU Worker 需要 NVIDIA Container Toolkit，并通过 profile 单独启动：

```bash
docker compose --profile gpu up -d code-gpu-worker
```

## 安全边界

仓库发现阶段不会安装依赖或执行第三方代码。依赖安装与项目测试必须由调用方
显式开启，并且只能在设置了时间、CPU、内存和网络限制的隔离沙箱中运行。
生产部署前请替换所有开发密码、启用 HTTPS，并使用专用密钥管理服务。
