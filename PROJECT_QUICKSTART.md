# Module Agent 项目快速上手

这份文档面向第一次进入本仓库的开发者。目标是让你能够：

1. 在本地启动项目并找到问题所在的模块；
2. 理解 Literature、Code、Validation 和 Supervisor 如何协作；
3. 按现有分层方式增加功能；
4. 独立实现“从论文 PDF 提取官方仓库链接”。

项目的长期任务状态见 [AGENT_ROADMAP.md](AGENT_ROADMAP.md)，生产化边界见
[M8_PRODUCTION_READINESS.md](M8_PRODUCTION_READINESS.md)。

> 安全提醒：如果密钥曾出现在终端、日志或测试失败输出中，请先在提供商后台
> 吊销并重新生成，再把新值写入本地 `.env`；不要提交 `.env`。

## 1. 先理解系统在做什么

这是一个模块化单体，多 Agent 共享一个应用仓库，但每个 Agent 有自己的领域模型、
应用服务和外部适配器。LangGraph 只负责总流程状态转换，不负责论文搜索或代码验证。

```text
用户创建 LiteratureRun
        ↓
Supervisor 启动总工作流
        ↓
RabbitMQ → Literature Worker
        ↓
OpenAlex / Semantic Scholar / Qwen
        ↓
论文结果写入 PostgreSQL
        ↓
LangGraph 从 checkpoint 恢复并暂停，等待用户选论文
        ↓
Code Agent 搜索可信仓库；证据不足时生成复现计划
        ↓
Validation Agent 做静态检查或显式沙箱检查
        ↓
Supervisor 汇总 ModuleBuildResult
```

几个重要边界：

- 专业 Agent 之间不直接互相调用，通过 Workflow 的类型化状态传递数据。
- HTTP Router 只接收请求和返回响应，不写核心业务判断。
- 数据库 Session、HTTP Request 等基础设施对象不能进入领域模型。
- 未经确认的仓库代码不能自动安装或执行。
- 单个外部来源失败时应当降级，不应让所有候选结果丢失。

## 2. 目录怎么找

```text
src/module_agent/
├── literature/       论文检索、筛选、方法画像、任务和消息队列
├── code/             仓库发现、证据评分、Git 获取和复现计划
├── validation/       静态检查和受控沙箱验证
├── supervision/      Supervisor 规则、Jev 建议与观察记录
├── workflow/         LangGraph 总图、人工中断、恢复和结果汇总
├── venue_catalog/    CCF、ICORE 和会议期刊目录
├── bootstrap/        把领域端口与具体适配器组装起来
├── shared/           数据库、HTTP、消息、配置等通用基础能力
├── api/              全局 FastAPI 中间件、异常和健康检查
├── cli/              Worker、迁移辅助等进程入口
└── main.py           FastAPI 应用入口
```

每个业务模块内部按需包含：

| 目录 | 放什么 | 不应放什么 |
|---|---|---|
| `domain/` | Pydantic 领域模型、枚举、Protocol 端口 | HTTP、SQLAlchemy、具体 SDK |
| `application/` | Agent、用例、组合规则 | FastAPI Request、数据库表 |
| `adapters/` | GitHub、Qwen、PDF、数据库、消息队列实现 | 跨 Agent 的流程调度 |
| `api/` | Router 和 HTTP schema | 仓库评分、筛选规则 |
| `workers/` | 消息消费者和进程生命周期 | 领域规则 |
| `bootstrap/` | 依赖注入和对象组装 | 新的业务算法 |

依赖方向应当保持：

```text
domain ← application ← api / workers
   ↑          ↑
   └──── adapters

bootstrap → domain + application + adapters
```

如果你不知道一个文件该放哪里，可以问：

- 它是“业务是什么”吗？放 `domain/`。
- 它是“业务怎么组合执行”吗？放 `application/`。
- 它是在调用某个外部技术吗？放 `adapters/`。
- 它只是在创建这些对象吗？放 `bootstrap/`。

## 3. 本地环境和常用命令

项目使用 uv 管理 Python 依赖：

```bash
uv sync
```

第一次初始化配置时才能执行下面的复制；已有 `.env` 时不要覆盖：

```bash
cp .env.example .env
```

启动完整环境：

```bash
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/api/health/
```

正常健康响应：

```json
{"status":"ok","service":"module-agent","environment":"development"}
```

`.env` 改动不会自动进入已经运行的容器。仅修改环境变量时不需要重新构建镜像，
但需要重新创建相关容器：

```bash
docker compose up -d --force-recreate api
```

检查 GitHub Token 是否进入容器，禁止把 Token 内容打印出来：

```bash
docker compose exec -T api sh -lc \
  'test -n "$GITHUB_TOKEN" && echo configured || echo missing'
```

查看日志：

```bash
docker compose logs -f api
docker compose logs -f literature-worker
docker compose logs -f literature-completion-worker
```

运行测试：

```bash
uv run pytest -q
uv run pytest tests/code -q
uv run pytest tests/code/test_github.py -q
```

做基本语法检查：

```bash
uv run python -m compileall -q src tests
```

运行包内模块时使用 `-m`：

```bash
uv run python -m module_agent.cli.run_literature_worker
```

不要直接运行 `src/module_agent/.../file.py`。直接运行文件会让 Python 丢失包上下文，
容易出现 `ModuleNotFoundError`。测试命令也不需要手工设置 `PYTHONPATH`，
`pyproject.toml` 已配置 `src`。

## 4. 一次请求经过哪些关键文件

### Literature 阶段

| 环节 | 文件 |
|---|---|
| HTTP 接口 | `literature/api/router.py` |
| 检索输入、结果和 Bundle | `literature/domain/search.py` |
| Literature Agent 图 | `literature/application/agent.py` |
| 多来源检索 | `literature/application/search.py` |
| OpenAlex | `literature/adapters/sources/openalex.py` |
| Semantic Scholar | `literature/adapters/sources/semantic_scholar.py` |
| 论文 ORM/Repository | `literature/adapters/database/` |
| RabbitMQ | `literature/adapters/messaging/` |

### Code 阶段

| 环节 | 文件 |
|---|---|
| Code 输入 | `code/domain/request.py` |
| 仓库候选和证据 | `code/domain/repository.py` |
| 最终 CodeArtifact | `code/domain/artifact.py` |
| 外部端口 | `code/domain/ports.py` |
| Code Agent 编排 | `code/application/agent.py` |
| 候选评分 | `code/application/scoring.py` |
| GitHub 搜索 | `code/adapters/github.py` |
| Git 浅克隆 | `code/adapters/git.py` |
| 依赖组装 | `bootstrap/factories/code_agent.py` |

Literature 的 `Paper` 不会自动变成 `CodePaperInput`。转换发生在：

```text
workflow/code_input.py
```

给论文模型新增字段后，最容易漏掉的就是这个转换边界。

### Workflow 阶段

| 环节 | 文件 |
|---|---|
| 总图 | `workflow/graph.py` |
| 图状态 | `workflow/domain.py` |
| 工作流服务 | `workflow/service.py` |
| Literature/选择协调 | `workflow/coordinator.py` |
| 生命周期 | `workflow/lifecycle.py`、`workflow/lifecycle_service.py` |
| API | `workflow/api/router.py` |

## 5. Pydantic 模型和 LangGraph State

项目中同时存在两类数据：

1. 领域边界使用 Pydantic 模型，例如 `SearchRequest`、`CodePaperInput`；
2. LangGraph checkpoint 使用可以序列化的字典、列表和基础类型。

基本规则：

```python
# 外部字典刚进入领域边界时，做校验
request = SearchRequest.model_validate(state["request"])

# 写回 LangGraph 状态时，转成 JSON 兼容字典
return {"request": request.model_dump(mode="json")}
```

对象已经确定是正确的 Pydantic 类型时，不需要重复 `model_validate()`。从数据库 JSON、
HTTP JSON、LangGraph state 或消息队列拿到普通字典时，才需要在边界处恢复类型。

不要把 Pydantic 对象直接长期放进 checkpoint；数据库/checkpoint 升级和跨进程恢复时，
普通 JSON 数据更稳定。

### 注释约定

- 类注释一句话说明该类承担的职责。
- 领域模型字段在字段上方说明业务含义，不重复类型本身。
- 方法注释一句话说明作用；参数和返回值能从类型看懂时不重复罗列。
- 只解释“为什么”和业务边界，不逐行翻译代码。
- 外部适配器应说明失败或缺失数据时的行为。
- 安全限制、降级原因和不明显的权重需要保留注释。

## 6. 数据库模型怎么改

项目区分领域实体和 ORM Model：

```text
domain/paper.py                         业务里的 Paper
adapters/database/models/paper.py      PostgreSQL 表映射
adapters/database/repositories/paper.py 两者之间转换
```

如果新增字段需要持久化，通常需要同步修改：

1. 领域模型；
2. ORM Model；
3. Repository 的保存和读取；
4. Alembic migration；
5. Repository 测试和 API/工作流转换测试。

生成迁移：

```bash
uv run alembic revision --autogenerate -m "add paper external ids"
```

生成后必须手工检查 `upgrade()` 和 `downgrade()`，不能直接相信自动生成结果。升级：

```bash
uv run alembic upgrade head
uv run alembic current
```

Docker 启动时 `migrate` 服务也会自动执行 `upgrade head`。

当前 `Paper` 已经持久化 `pdf_url`，所以只实现 PDF 提取时不需要新增数据库字段；只需要
把 `pdf_url` 传入 `CodePaperInput`。如果以后增加 `external_ids`，才需要 JSONB 迁移。

## 7. 当前 GitHub 搜索为什么不够

现有 `GitHubRepositorySearcher` 使用完整论文标题搜索仓库名、描述和 README：

```text
"paper title" in:name,description,readme
```

论文标题出现在 README 里只能证明该仓库“提到过论文”，不能证明它是官方实现。目前标题
证据权重是 `0.35`，默认可信门槛是 `0.7`，所以这些候选会被安全拒绝。

PDF 中由论文作者直接提供的 GitHub 链接是更强证据。它可以使用已有的
`RepositoryEvidenceType.PAPER_URL`，但仍需经过 URL 规范化、GitHub 元数据补全和现有评分器。

不要通过降低 `CODE_REPOSITORY_CONFIDENCE_THRESHOLD` 解决问题；这会让无关第三方仓库
更容易被克隆。

## 8. 功能任务：从 PDF 提取仓库链接

### 8.1 目标和非目标

输入：

```text
CodePaperInput.pdf_url
```

输出：

```text
list[RepositoryCandidate]
```

成功条件：

- 从 PDF 超链接注解或正文中识别 GitHub 仓库地址；
- 只保留仓库根地址，例如 `https://github.com/owner/repo`；
- 记录链接来自哪个 PDF、哪一页；
- 与现有 GitHub 搜索结果合并并去重；
- PDF 不存在、不可下载或无法解析时，现有 GitHub 搜索仍然可用；
- 不能执行 PDF 中链接的仓库代码。

第一版不需要：

- OCR 扫描版 PDF；
- 从 PDF 复现算法；
- 下载仓库依赖、模型权重或数据集；
- 支持所有代码托管平台。先只支持 GitHub。

### 8.2 推荐数据流

```text
CodePaperInput
  ├─ GitHubRepositorySearcher ──────┐
  │                                 │
  └─ PdfRepositorySearcher          ├─ 合并、按 URL 去重
       ├─ 安全下载 PDF              │
       ├─ pdfplumber 提取链接       │
       └─ 构造带 PAPER_URL 证据的候选┘
                                     ↓
                         RepositoryScoringService
                                     ↓
                         达到 0.7 才允许浅克隆
```

PDF 提取是 Code Agent 的适配器，不是一个新 Agent，也不应该写进 Router 或 Workflow。

### 8.3 建议修改的文件

第一轮只需要关注：

```text
src/module_agent/code/domain/request.py
src/module_agent/workflow/code_input.py
src/module_agent/code/adapters/pdf_repository.py       # 新建
src/module_agent/code/application/repository_search.py # 新建
src/module_agent/bootstrap/factories/code_agent.py
tests/code/test_pdf_repository.py                      # 新建
tests/code/test_repository_search.py                   # 新建
tests/workflow/test_code_input.py
```

### 8.4 第一步：把 PDF URL 传进 Code Agent

在 `CodePaperInput` 增加：

```python
pdf_url: str | None = None
```

然后在 `SelectedPaperCodeInputLoader` 构造输入时增加：

```python
pdf_url=paper.pdf_url,
```

验收点：

- 有 PDF 的 `Paper` 转换后仍有相同的 `pdf_url`；
- 没有 PDF 时为 `None`，不会报错；
- 旧 checkpoint 中没有该字段时仍能恢复，因为字段有默认值。

### 8.5 第二步：实现 PDF 仓库搜索适配器

新类继续实现已有 `RepositorySearcher` Protocol，不必修改 `CodeAgent`：

```python
class PdfRepositorySearcher:
    async def search(
        self,
        paper: CodePaperInput,
        *,
        limit: int = 10,
    ) -> list[RepositoryCandidate]:
        ...
```

建议把方法拆小：

```text
search()
  ├─ _download_pdf()
  ├─ _extract_links()
  ├─ _normalize_github_repository_url()
  └─ _build_candidate()
```

`pdfplumber` 是同步库，不要直接阻塞 FastAPI 事件循环：

```python
links = await asyncio.to_thread(self._extract_links, pdf_bytes)
```

提取时检查两类内容：

1. PDF annotation 中的可点击链接；
2. `page.extract_text()` 中显示出来的 URL。

可先使用正则识别：

```text
https://github.com/<owner>/<repository>
```

URL 规范化要求：

- 只接受 `https://github.com`；
- owner 和 repository 都必须存在；
- 去掉末尾 `.git`、`/` 和标点；
- `/tree/main`、`/issues/1` 等链接统一截成仓库根地址；
- 排除 `github.com/login`、`github.com/features` 等非仓库路径；
- URL 去重时忽略大小写和末尾 `/`；
- `javascript:`、`file:`、本机路径一律拒绝。

候选至少需要：

```python
RepositoryCandidate(
    provider="github",
    full_name="owner/repository",
    repository_url="https://github.com/owner/repository",
    owner_login="owner",
    evidence=[
        RepositoryEvidence(
            evidence_type=RepositoryEvidenceType.PAPER_URL,
            description="Repository URL found in paper PDF page 7",
            weight=0.95,
            source_url=paper.pdf_url,
        )
    ],
)
```

不要在 PDF 适配器里决定最终选择哪个仓库。它只负责提供候选和证据，最终置信度仍由
`RepositoryScoringService` 计算。

### 8.6 PDF 下载的安全边界

PDF URL 是外部输入，下载器至少应限制：

- 只允许 HTTPS；
- 连接和读取超时；
- 最大文件大小，例如 20 MiB；
- 最大解析页数，例如 50 页；
- 检查 `Content-Type` 或 `%PDF-` 文件头；
- 不向 PDF 地址发送 GitHub、Qwen 等任何密钥；
- 不访问 localhost、私有网段和云元数据地址；
- 重定向后的每一个地址也要重新执行 URL 安全检查；
- 解析错误返回空候选和 warning，不执行 PDF 内嵌对象。

最小版本如果暂时没有通用 SSRF 防护，可以先只允许可信论文域名，并把允许列表写成配置，
不要直接放开任意主机。常见测试域名不能进入生产允许列表。

不要把 PDF 原始内容写进日志。日志只记录 URL 域名、字节数、页数、候选数量、耗时和错误
类型。

### 8.7 第三步：组合两个搜索来源

现有 `CodeAgent` 只接收一个 `RepositorySearcher`，因此新增一个组合实现：

```python
class CompositeRepositorySearcher:
    def __init__(self, searchers: Sequence[RepositorySearcher]) -> None:
        self.searchers = tuple(searchers)

    async def search(
        self,
        paper: CodePaperInput,
        *,
        limit: int = 10,
    ) -> list[RepositoryCandidate]:
        ...
```

组合器的职责：

- 并发执行 PDF 和 GitHub 搜索；
- 使用 `asyncio.gather(..., return_exceptions=True)` 隔离单来源失败；
- 按规范化 `repository_url` 去重；
- 同一仓库的 evidence 合并而不是覆盖；
- 优先保留字段更完整的候选；
- 合并后再应用总数量限制；
- 所有来源失败时才向上抛出明确异常。

它属于 Code 模块的应用编排，建议放在：

```text
code/application/repository_search.py
```

### 8.8 第四步：在 Bootstrap 中组装

修改 `bootstrap/factories/code_agent.py`：

```text
GitHubRepositorySearcher ─┐
                          ├→ CompositeRepositorySearcher → CodeAgent
PdfRepositorySearcher ───┘
```

`CodeAgent`、Workflow 和 Router 不需要知道 PDF 是怎么解析的。如果为了接入该功能而需要在
Router 中导入 `pdfplumber`，说明分层位置错了。

注意 HTTP 客户端生命周期：成熟实现应由应用 lifespan 创建和关闭客户端，再从 Bootstrap
注入。不要为每一页 PDF 创建一个客户端，也不要忘记关闭长期客户端。

## 9. 这个功能该怎么测试

单元测试不能依赖真实 GitHub 或真实论文网站，否则会受到网络、限流和内容变化影响。

### PDF 搜索器测试

至少覆盖：

1. `pdf_url=None` 返回空列表；
2. 从可点击 annotation 提取 URL；
3. 从普通正文提取 URL；
4. `.git`、`/tree/main` 被规范化为仓库根地址；
5. 同一 URL 出现多次只返回一个候选；
6. 非 GitHub URL 和 GitHub 非仓库页面被忽略；
7. 超大 PDF、非 PDF 响应和超时被安全拒绝；
8. evidence 包含 PDF URL 和页码；
9. PDF 解析异常不会执行或写出任何文件。

HTTP 使用 `httpx.MockTransport`，参考：

```text
tests/code/test_github.py
```

URL 规范化最好写成纯函数，这样大多数边界不需要真的构造 PDF：

```python
def normalize_github_repository_url(value: str) -> str | None:
    ...
```

### 组合搜索器测试

至少覆盖：

- 两个来源成功时合并；
- 同一仓库合并 evidence；
- PDF 失败时保留 GitHub 结果；
- GitHub 失败时保留 PDF 结果；
- 所有来源失败时抛错；
- 最终候选不超过 limit。

### Code Agent 回归测试

至少覆盖：

- PDF 直链证据达到门槛后走安全浅克隆路径；
- 只有低分 GitHub 标题证据时仍生成复现计划；
- PDF 不存在时行为和改动前一致。

建议按以下顺序运行：

```bash
uv run pytest tests/code/test_pdf_repository.py -q
uv run pytest tests/code/test_repository_search.py -q
uv run pytest tests/code -q
uv run pytest -q
```

不要在自动化单元测试里真的克隆仓库或执行论文实验。

## 10. 实现顺序清单

按顺序完成，出现问题时容易定位：

- [x] `CodePaperInput` 增加可选 `pdf_url`。
- [x] `SelectedPaperCodeInputLoader` 传递 `paper.pdf_url`。
- [x] 为上述转换补测试。
- [x] 写 GitHub 仓库 URL 规范化纯函数及测试。
- [x] 写 PDF 字节解析和链接提取测试。
- [x] 实现受限 PDF 下载。
- [x] 构造带 `PAPER_URL` evidence 的 `RepositoryCandidate`。
- [x] 将 GitHub、PDF、论文落地页和补充材料搜索合并并去重。
- [x] 在 Bootstrap 中装配组合后的仓库搜索器。
- [x] 跑 Code 模块测试。
- [x] 跑全部测试。
- [ ] 使用一篇明确在 PDF 中提供代码链接的论文做只读真实验收。
- [x] 确认默认发现流程不会安装依赖、执行仓库代码或输出密钥。

## 11. 常见错误

### “配置了 GitHub，为什么仍然没有仓库？”

Token 只提高 API 限额，不会自动把第三方仓库识别成官方仓库。最终是否采用取决于 evidence
和 confidence threshold。

### `model_validate()` 到处都是

只在字典进入领域边界时使用。对象已经是 `CodePaperInput` 时直接使用。

### PDF 报错导致 CodeArtifact 直接 failed

PDF 是附加来源，应该由组合搜索器隔离失败。只要 GitHub 搜索仍有结果，就继续处理；没有
可信结果时回退复现计划。

### 为了调用新类在 Router 里创建实例

不要这样做。具体实现统一在 `bootstrap/factories/code_agent.py` 组装。

### 修改 `.env` 后代码仍认为变量为空

容器没有自动重新读取 `.env`，使用 `docker compose up -d --force-recreate api`。

### PDF 里有链接但提取不到

先判断它属于哪一种：annotation、正文文本、换行断开的 URL，还是扫描图片。第一版只保证
前两种；扫描 PDF 需要 OCR，应作为后续独立功能。

## 12. 完成定义

这个功能不是“正则找到了一个 GitHub 字符串”就完成。最终应满足：

- PDF URL 从 Literature 数据稳定传入 Code Agent；
- PDF 解析不会阻塞事件循环；
- 下载有超时、大小和网络地址限制；
- 候选带来源证据，可解释为什么被接受；
- 与现有 GitHub 候选正确合并；
- 任一外部来源失败都能安全降级；
- 未达到可信门槛的仓库不会被克隆；
- 自动化测试覆盖成功、失败、去重和安全边界；
- 全量测试通过；
- 真实验收期间不执行论文代码和实验。

做到这些之后，“PDF 提取仓库”才真正接入了现有多 Agent 工作流，而不是一个孤立脚本。
