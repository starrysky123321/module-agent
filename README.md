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
  暂停、恢复、重试与追踪。
- 提供 Prometheus 指标和 Grafana dashboard。

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

外部模型或数据源需要在本地 `.env` 中填写对应密钥；`.env` 不会提交到 Git。

## 验证

```bash
uv run pytest -q
uv run alembic check
docker compose config --quiet
```

GPU Worker 需要 NVIDIA Container Toolkit，并通过 profile 单独启动：

```bash
docker compose --profile gpu up -d code-gpu-worker
```

## 文档

- [项目快速上手](PROJECT_QUICKSTART.md)
- [系统架构](ARCHITECTURE.md)
- [Agent 开发路线图](AGENT_ROADMAP.md)
- [生产就绪说明](M8_PRODUCTION_READINESS.md)
- [GitHub 开发流程](GIT_WORKFLOW.md)

## 安全边界

仓库发现阶段不会安装依赖或执行第三方代码。依赖安装与项目测试必须由调用方
显式开启，并且只能在设置了时间、CPU、内存和网络限制的隔离沙箱中运行。
生产部署前请替换所有开发密码、启用 HTTPS，并使用专用密钥管理服务。
