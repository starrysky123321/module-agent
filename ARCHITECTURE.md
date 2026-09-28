# Module Agent 架构

新开发者先阅读 [PROJECT_QUICKSTART.md](PROJECT_QUICKSTART.md)，开发状态和任务清单见
[AGENT_ROADMAP.md](AGENT_ROADMAP.md)。

## 总体流程

```text
ModuleBuildRequest
  -> Supervisor Agent
  -> Literature Agent
  -> 等待用户选择论文
  -> Code Agent
  -> Validation Agent
  -> Supervisor Agent 汇总结果
```

LangGraph 负责状态转换、checkpoint、interrupt 和恢复。专业模块之间不直接调用，统一通过 Workflow 的类型化状态交换数据。

## 目录组织

项目采用按业务能力组织的模块化单体：

```text
src/module_agent/
├── literature/       文献检索、筛选、持久化和异步任务
├── workflow/         LangGraph 总工作流与协调服务
├── code/             可信代码发现、安全获取和论文复现计划
├── validation/       代码产物静态检查与受控沙箱验证
├── supervision/      总流程决策、Jev 建议和决策可观测性
├── venue_catalog/    会议期刊、CCF 和 ICORE 评级
├── shared/           配置及通用技术客户端
├── bootstrap/        对象组装和依赖注入
├── api/              全局 HTTP 生命周期、健康检查和异常处理
├── cli/              进程入口和维护命令
└── main.py            FastAPI 应用入口
```

测试目录使用相同的业务模块划分。

## 模块内部结构

业务模块按需使用以下目录：

- `domain/`：领域模型、输入输出契约和端口协议。
- `application/`：Agent 和用例服务。
- `adapters/`：数据库、外部 API、LLM、缓存和消息队列实现。
- `api/`：该业务模块的 HTTP 路由和 HTTP schema。
- `workers/`：该业务模块拥有的后台消费者。

例如 Literature 模块：

```text
literature/
├── domain/
├── application/
├── adapters/
│   ├── database/
│   ├── llm/
│   ├── messaging/
│   └── sources/
├── api/
└── workers/
```

## 依赖方向

```text
domain <- application <- api/workers
   ^           ^
   └──────── adapters

bootstrap -> 所有需要被组装的模块
shared    -> 不依赖任何业务模块
```

具体规则：

1. `domain` 不导入 `application` 或 `adapters`。
2. `application` 面向 `domain` 中定义的协议编程。
3. `adapters` 实现领域协议并连接外部系统。
4. `api` 和 `workers` 只负责入口与生命周期，不放业务规则。
5. `bootstrap` 是唯一允许同时了解抽象和具体实现的组装层。
6. `shared` 只放真正跨模块的基础能力，不能反向导入业务模块。

## 常用文件位置

| 要找的内容 | 位置 |
|---|---|
| Literature Agent 图 | `literature/application/agent.py` |
| 检索请求、结果和 Bundle | `literature/domain/search.py` |
| OpenAlex、Semantic Scholar | `literature/adapters/sources/` |
| Qwen 文献分析实现 | `literature/adapters/llm/` |
| Literature ORM 和仓库 | `literature/adapters/database/` |
| RabbitMQ 文献消息 | `literature/adapters/messaging/` |
| Literature Worker | `literature/workers/` |
| Literature HTTP API | `literature/api/` |
| 总 LangGraph | `workflow/graph.py` |
| Workflow 恢复与协调 | `workflow/service.py`、`workflow/coordinator.py` |
| Workflow 生命周期与节点轨迹 | `workflow/lifecycle.py`、`workflow/observation.py` |
| CodeRun/ValidationRun 生命周期 | `code/application/run.py`、`validation/application/run.py` |
| Supervisor 规则和 Jev 策略 | `supervision/application/` |
| Supervisor 观察数据和统计 | `supervision/adapters/database/`、`supervision/api/` |
| CCF、ICORE | `venue_catalog/adapters/rankings/` |
| Code Agent 输入和产物 | `code/domain/` |
| GitHub 仓库搜索 | `code/adapters/github.py` |
| 仓库匹配评分 | `code/application/scoring.py` |
| Git 安全拉取与工作区 | `code/adapters/git.py`、`code/adapters/workspace.py` |
| Code Agent 编排 | `code/application/agent.py` |
| Code Artifact 查询 API | `code/api/router.py` |
| FastAPI 依赖注入 | `bootstrap/api_dependencies.py` |
| Worker 对象组装 | `bootstrap/worker_factories.py` |
| 配置和公共客户端 | `shared/` |
| 请求鉴权与关联日志 | `api/auth.py`、`api/request_context.py`、`shared/context.py` |

## 当前运行状态

- Literature Agent 已接入 OpenAlex、Semantic Scholar 和 Qwen。
- LiteratureRun 通过 RabbitMQ 异步执行。
- Literature 完成事件会自动恢复 PostgreSQL 中的 LangGraph checkpoint。
- 工作流能够暂停等待论文选择，并在确认后依次运行 Code Agent 和 Validation Agent，最终进入 `completed`。
- Code Agent 已完成 GitHub 搜索、证据评分、安全浅克隆、commit 固定、复现计划回退和产物查询，并通过两条真实路径联调。
- Validation Agent 已完成结构化静态检查、显式沙箱检查和报告查询。
- Supervisor 已接管 LangGraph 条件路由、有限重试、失败终止和最终汇总。
- Jev 支持默认安全的 shadow 模式，以及只能高置信度否决重试的 guarded 模式；观察结果会独立持久化并提供统计、明细和人工评审就绪接口。
- CodeRun、ValidationRun 和 ModuleWorkflowRun 使用独立短事务持久化，运行中和失败状态可被其他请求查询。
- Workflow 支持持久化 deadline、协作式取消、超时失败、节点执行轨迹和跨进程 trace ID。
- 生产模式要求 Bearer token 和安全连接配置；应用容器以 UID 10001、只读根文件系统和零 Linux capability 运行。

## 新增代码约定

1. 新增文献来源放在 `literature/adapters/sources/`，并在来源注册表中注册。
2. 新增 Literature 用例放在 `literature/application/`，不要放到 `shared/`。
3. 只有多个业务模块都需要且不包含业务规则的代码才能进入 `shared/`。
4. 新建外部实现时，先在所属模块的 `domain/` 定义协议。
5. 新增测试时镜像源码模块目录。
6. Agent 之间只交换明确的领域对象，不交换数据库 Session 或 HTTP Request。
