# Module Agent 开发路线图

更新日期：2026-09-28

本文档用于定义每个 Agent 的职责、输入输出、功能清单和验收标准。每完成一项就在对应任务前标记 `[x]`。

## 状态说明

- `[x]`：已经实现并通过相应测试。
- `[ ]`：尚未完成。
- “待真实联调”：代码和 Mock 测试已完成，但外部系统的真实调用还没有验证。

## 总体目标

```text
ModuleBuildRequest
  → Supervisor Agent
  → Literature Agent
  → 人工选择论文
  → Code Agent
  → Validation Agent
  → Supervisor Agent 汇总结果
  → ModuleBuildResult
```

专业 Agent 之间不直接调用。它们只通过总工作流中的类型化状态交换数据，由 Supervisor Agent 决定下一步。

## 里程碑

- [x] M0：基础设施和异步 Literature Worker 可运行。
- [x] M1：Literature Agent 确定性检索 MVP 可运行。
- [x] M2：Literature Agent 接入 LLM 查询规划和论文语义分析。
- [x] M3：人工选择论文，并支持工作流暂停和恢复。
- [x] M4：Code Agent 获取和整理可信代码仓库。
- [x] M5：Code Agent 在无可信代码时生成复现方案。
- [x] M6：Validation Agent 验证代码产物。
- [x] M7：Supervisor Agent 和 ModuleBuildWorkflow 串联全流程。
- [x] M8：完成端到端测试、可观测性和生产安全约束。

---

## 1. Supervisor Agent

### 职责

Supervisor Agent 是总协调者。它不负责搜索论文、编写代码或执行验证，而是读取工作流状态并决定下一步交给哪个专业 Agent。

### 输入

- `ModuleGraphState`
- 用户最初的 `ModuleBuildRequest`
- Literature、Code、Validation 阶段的已有产物
- 当前状态、错误和人工选择结果

### 输出

- `SupervisorDecision`
  - `next_step`
  - `status`
  - `reason`

### 功能清单

- [x] 定义 `WorkflowStatus` 和 `SupervisorStep` 枚举。
- [x] 定义 `ModuleGraphState` 基础状态结构。
- [x] 创建 `SupervisorAgent` 代码骨架。
- [x] 校验用户请求和工作流状态是否具备进入下一阶段的必要信息。
- [x] 根据状态选择 Literature、Paper Selection、Code、Validation 或 Finish。
- [x] 识别专业 Agent 的失败状态，并决定重试、等待用户还是终止。
- [x] 防止非法状态跳转，例如未选择论文就启动 Code Agent。
- [x] 生成用户可理解的阶段进度和决策原因。
- [ ] 接入 LLM，用于理解复杂用户目标和补充要求。
- [x] 为 Jev 决策建议增加结构化输出校验和确定性 fallback。
- [x] 编写 Supervisor 状态路由单元测试。
- [x] 实现 Jev shadow 策略、独立持久化和统计查询。
- [x] 实现默认关闭且只能否决重试的 Jev guarded 策略。

### 完成标准

- 给定任意合法 `ModuleGraphState`，Supervisor 都能返回合法且可解释的下一步。
- 非法状态不会启动下游 Agent。
- LLM 不可用时仍能通过规则完成基本调度。

---

## 2. Literature Agent

### 职责

根据用户的研究方向、时间范围、关键词、会议期刊和质量要求检索文献，统一元数据，筛选并持久化候选论文，向总工作流输出稳定的 `LiteratureBundle`。

### 输入

- `SearchRequest`
  - 研究主题和描述
  - 开始日期和结束日期
  - 关键词和排除关键词
  - 指定会议或期刊
  - CCF/ICORE 等质量要求
  - 最大结果数

### 输出

- `LiteratureBundle`
  - 实际检索词
  - 原始候选论文
  - 最终筛选论文
  - 已持久化论文
  - 方法画像及其证据和置信度
  - 模型调用耗时、成功或回退、错误类型
  - warnings

### 2.1 查询规划

- [x] 根据 `topic + keywords` 生成基础检索词。
- [x] 对空关键词和重复关键词进行基础处理。
- [x] 定义 `LiteratureQueryPlanner` 接口。
- [x] 实现当前规则规划器，作为无 LLM 时的 fallback。
- [x] 将 `LiteratureQueryPlanner` 注入 `LiteratureAgent` 和 Worker。
- [x] 实现通用 primary/fallback 规划器并记录降级 warning。
- [x] 实现 Qwen 查询规划适配器并通过 Mock 测试。
- [x] 实现 Qwen 异步客户端生命周期管理器。
- [x] 接入 LLM 规划器，并完成 Qwen 真实调用验证。
- [x] 支持中文研究需求转英文检索词。
- [x] 生成同义词、缩写、全称和相关技术术语。
- [x] 对 LLM 输出进行数量、长度、重复项和空值校验。
- [x] 当 LLM 调用失败时自动退回规则规划器。

### 2.2 网络文献来源

- [x] 定义可扩展的 `LiteratureSource` 接口。
- [x] 实现 OpenAlex 网络检索。
- [x] 解析 OpenAlex DOI、作者、摘要、来源、PDF 和开放获取信息。
- [x] 实现 Semantic Scholar 数据解析。
- [x] 实现 Semantic Scholar HTTP 请求和日期过滤。
- [x] 将 Semantic Scholar 注册到来源注册表。
- [x] 完成 Semantic Scholar 真实网络联调。
- [x] 根据真实限流行为完善超时、429 和重试策略。
- [ ] 评估是否增加 arXiv、Crossref 或 DBLP 来源。
- [x] 为每个来源记录查询词、请求耗时、返回数量和失败类型，并持久化到运行记录。

### 2.3 多来源可靠性

- [x] 并发调用同一次搜索请求的多个来源。
- [x] 单个来源失败时保留其他来源的结果。
- [x] 将来源失败记录为 warning。
- [x] 所有来源都失败时抛出异常，让 RabbitMQ 重试。
- [x] 对多次检索产生的重复 warning 去重。
- [ ] 为来源设置独立超时和可配置开关。
- [x] 为 Semantic Scholar 增加来源级限流、退避重试和熔断恢复策略。

### 2.4 论文归一化、去重和筛选

- [x] 定义统一的 `PaperSearchResult`。
- [x] 共享 DOI 规范化逻辑。
- [x] 优先根据 DOI 去重。
- [x] 无 DOI 时根据规范化标题去重。
- [x] 对标题的 Unicode、大小写、标点和连字符进行统一归一化。
- [x] 合并 DOI 不同但规范化标题相同的版本，并优先保留正式发表记录。
- [x] 支持指定会议和期刊筛选。
- [x] 支持排除关键词筛选。
- [x] 支持 CCF 和 ICORE 等级筛选。
- [x] 按引用量排序并限制最终数量。
- [x] 增加与用户主题的语义相关性评分。
- [ ] 设计引用量、相关性、发表时间和场所质量的综合排序。
- [ ] 保存论文被接受或排除的原因，便于解释结果。

### 2.5 论文语义信息补全

- [x] 保存 DOI、摘要、PDF、落地页和论文开放获取状态。
- [x] 使用 LLM 提取论文解决的问题。
- [x] 使用 LLM 识别算法或模块类型。
- [x] 提取关键方法、输入、输出和适用任务；无证据时保留空值。
- [x] 区分“论文开放获取”和“代码开源”；无许可证的公开仓库单独标记为 source_available。
- [x] 由 Code Agent 搜索并验证论文对应的官方代码仓库，并把结果回写论文查询模型。
- [x] 为语义提取结果保存证据来源和置信度。

### 2.6 数据持久化与任务接口

- [x] 将论文保存到 PostgreSQL。
- [x] 将本次运行的论文方法画像保存到 PostgreSQL，并通过论文结果 API 返回。
- [x] 为 Qwen 规划、相关性评分和方法提取设置可配置超时，超时后保留规则回退。
- [x] 持久化每次 Qwen 调用的阶段、模型、篇数、耗时、结果和错误类型，并通过任务状态 API 查询。
- [x] 持久化会议期刊和 CCF/ICORE 评级。
- [x] 使用 Redis 缓存会议期刊评级。
- [x] 创建 LiteratureRun、状态和论文关联表。
- [x] 提供创建任务接口。
- [x] 提供任务入队接口。
- [x] 提供任务状态查询接口。
- [x] 提供某次任务的有序论文结果接口。
- [x] 实现 RabbitMQ 主队列、重试和死信队列。
- [x] Literature Worker 完成后发布完成事件，由独立 Worker 自动恢复总工作流。
- [x] 实现普通 Worker 和死信 Worker。
- [x] Docker 化 API、Worker、PostgreSQL、Redis、RabbitMQ 和迁移任务。
- [x] 在 Docker 中重建并联调最新的 Semantic Scholar 代码。
- [x] 使用真实 HTTP、PostgreSQL、RabbitMQ、OpenAlex、Semantic Scholar 和 Qwen 跑通 Literature 阶段。

### 2.7 Literature Agent 完成标准

- [x] 中文或英文请求都能生成有效英文检索词。
- [x] 至少两个真实网络来源完成联调。
- [x] 一个来源失败时任务仍可返回其他来源结果。
- [x] 筛选结果能持久化并通过 API 查询。
- [x] 每篇进入 Code 阶段的论文包含研究问题、模块类型和代码开源状态；未处理论文保持 unknown。
- [x] 结果具备可解释的入选理由。

---

## 3. 人工论文选择阶段

这一阶段不是 Agent，而是 Literature Agent 和 Code Agent 之间必须存在的人机协作边界。

### 输入

- Literature Agent 推荐的有序论文列表
- 用户补充的代码要求

### 输出

- `selected_paper_ids`
- 更新后的 `code_requirements`

### 功能清单

- [x] 数据结构中预留 `selected_paper_ids`。
- [x] 已提供 LiteratureRun 论文结果查询接口。
- [x] 提供提交论文选择的 API。
- [x] 校验所选论文必须属于当前 LiteratureRun。
- [x] 保存用户选择及选择时间。
- [x] 在 LangGraph 中使用 interrupt 暂停工作流。
- [x] 用户提交选择后从 checkpoint 恢复工作流。
- [ ] 支持用户要求重新检索或调整筛选条件。
- [x] 防止重复提交导致 Code Agent 重复执行。

### 完成标准

- 工作流在论文选择前不会启动 Code Agent。
- 进程重启后仍能恢复等待选择的任务。
- 用户只能选择当前任务中存在的论文。

---

## 4. Code Agent

### 职责

根据用户选中的论文和补充要求，优先寻找并获取官方代码；没有可用官方代码时，生成可追踪的复现计划和实现产物。

### 输入

- `CodeAgentRequest`
  - `LiteratureBundle`
  - `selected_paper_ids`
  - `code_requirements`

### 输出

- `list[CodeArtifact]`
  - 对应论文
  - `official` 或 `reproduced`
  - 状态
  - 仓库地址
  - 本地工作目录

### 4.1 代码来源发现

- [x] 定义 `CodeAgentRequest` 和 `CodeArtifact` 初始结构。
- [x] 创建 `CodeAgent` 代码骨架。
- [x] 从论文落地页、PDF 正文/批注和补充材料链接查找官方仓库。
- [x] 搜索 GitHub 中的候选仓库并读取 README 和仓库元数据。
- [x] 使用确定性规则验证仓库与论文标题、作者和 DOI 的对应关系。
- [x] 区分官方仓库、作者仓库和第三方复现。
- [x] 检查许可证、默认分支、固定提交和归档状态。
- [x] 保存仓库发现证据和置信度。

### 4.2 官方代码获取

- [x] 安全浅克隆确认过的可信仓库。
- [x] 固定 commit SHA，确保结果可复现。
- [x] 静态解析 README、依赖文件、模型权重和数据要求，不执行仓库代码。
- [x] 根据入口文件、main guard 和论文关键词识别可复用模块候选。
- [x] 根据用户要求关键词给出仓库文件匹配结果。
- [x] 禁止自动执行不可信安装脚本。
- [x] 记录许可证信息。

### 4.3 无官方代码时复现

- [x] 从论文元数据和方法画像生成算法步骤、输入和输出计划。
- [x] 生成结构化复现计划，记录缺失信息和风险。
- [x] 明确标记产物为 `reproduction_plan`，不能伪装成官方代码。
- [x] 创建隔离的代码工作区；第一版不自动安装第三方依赖。
- [x] 生成可导入、可运行的最小工程骨架，并明确标记论文算法逻辑仍待实现和验证。
- [x] 生成结构化复现计划、示例输入、包配置和使用说明。
- [x] 记录无法确认的问题和警告。
- [ ] 支持用户对复现范围进行补充和确认。

### 4.4 Code Agent 任务生命周期

- [x] 定义 CodeRun 状态和数据库模型。
- [x] 定义代码产物、仓库证据和文件清单实体。
- [x] 实现 Code Worker 和消息队列（CPU/GPU 分队列，完成事件恢复 workflow）。
- [x] 实现按 workflow attempt 幂等、Supervisor 重试、协作式取消和失败状态持久化。
- [x] 提供 Workflow 状态中的 CodeArtifact 查询 API。
- [x] 为每个选中论文独立记录执行结果。

### 4.5 Code Agent 完成标准

- 给定一篇选中论文，能输出官方代码产物或明确标记的复现产物。
- 每个产物都能追溯到论文、仓库、commit 和生成过程。
- 不自动执行未经验证的不可信代码。
- 失败时能提供结构化原因，而不是只返回异常文本。

---

## 5. Validation Agent

### 职责

在隔离环境中验证 Code Agent 的产物是否可安装、可导入、可运行，并生成结构化验证报告。

### 输入

- `ValidationRequest`
  - `literature_run_id`：关联上游文献任务
  - `artifacts`：待验证的 `list[CodeArtifact]`
  - `policy`：静态或沙箱模式，以及网络、超时、CPU、内存限制
  - `user_requirements`：可选的用户验收要求

### 输出

- `list[ValidationReport]`
  - 每个报告只对应一个 `CodeArtifact`
  - `passed`、`partial` 或 `failed`
  - 结构化检查项、证据、警告与错误
  - 是否实际执行过代码

### 功能清单

- [x] 将 Validation 领域契约迁移到 `validation/domain`，定义请求、安全策略、检查项和报告。
- [x] 创建 `ValidationAgent` 代码骨架。
- [x] 校验代码产物和清单是否完整。
- [x] 在隔离容器中创建依赖环境。
- [x] 执行静态语法和导入检查。
- [x] 执行最小 smoke test。
- [x] 执行项目自带测试，但设置时间、CPU、内存和网络限制。
- [ ] 验证示例输入能产生符合格式的输出。
- [ ] 对比论文描述的输入、输出和关键行为。
- [ ] 区分环境失败、依赖失败、代码失败和结果偏差。
- [ ] 扫描危险脚本、敏感信息和明显的供应链风险。
- [x] 生成机器可读和用户可读的验证报告。
- [ ] 将失败反馈给 Supervisor，由其决定重试 Code Agent 或结束任务。

### 完成标准

- 每个 CodeArtifact 都对应一份 ValidationReport。
- 验证过程在受限、可销毁的环境中运行。
- 报告包含执行命令、退出状态、关键日志和结论依据。
- `passed`、`partial`、`failed` 有明确且稳定的判定标准。

---

## 6. ModuleBuildWorkflow

### 职责

使用 LangGraph 串联 Supervisor、Literature、人工选择、Code 和 Validation 阶段，并负责持久化、暂停、恢复和终止整个任务。

### 功能清单

- [x] 定义 `ModuleBuildWorkflow` 构造结构。
- [x] 定义总工作流状态的初始字段。
- [x] 注册 Supervisor 节点。
- [x] 注册 Literature 节点。
- [x] 注册人工论文选择节点。
- [x] 注册 Code 节点。
- [x] 注册 Validation 节点。
- [x] 添加基于 `SupervisorDecision` 的条件边。
- [x] 接入持久化 checkpointer。
- [x] 使用稳定的 workflow/thread ID。
- [x] 实现人工 interrupt 和 resume。
- [x] Literature Agent 异步完成后自动从等待节点恢复到论文选择节点。
- [x] 实现工作流级取消、超时和失败状态。
- [x] 保存每个节点的脱敏输入、输出摘要和执行时间。
- [x] 提供创建、查询、恢复和取消总任务的 API。
- [x] 编写进程重启后的恢复测试。
- [x] 编写完整端到端测试。

### 完成标准

- 总工作流能够从用户请求运行到最终验证报告。
- 人工选择阶段可以跨进程暂停和恢复。
- 任一 Agent 失败时，总状态和错误原因可查询。
- 同一个任务重复投递不会产生重复代码产物。

---

## 7. 公共工程能力

### 已完成

- [x] uv 项目环境和依赖锁定。
- [x] FastAPI 基础应用和全局异常处理。
- [x] PostgreSQL、SQLAlchemy 和 Alembic。
- [x] Redis 缓存。
- [x] RabbitMQ quorum queue、重试和死信处理。
- [x] Docker Compose 基础运行环境。
- [x] 单元测试和部分集成测试基础。
- [x] 按 Literature、Workflow、Venue Catalog 等业务能力完成模块化单体目录整理。
- [x] 统一 request、trace、workflow、agent run 和 message 关联日志。
- [x] 持久化节点耗时并提供 workflow 成功率、耗时和节点失败指标。
- [x] 增加生产配置检查、Bearer API 保护、非 root 只读应用容器。
- [x] 增加 CI 测试、迁移验证和镜像构建流程。

### 待完成

- [x] 增加 RabbitMQ 队列积压指标和 LLM token 用量汇总。
- [ ] 集中管理外部 API 超时、退避和速率限制。
- [ ] 对 LLM Prompt、模型版本和结构化输出进行版本管理。
- [ ] 增加用户级权限、任务归属和数据隔离。
- [x] 定义当前阶段的存储方案：PDF 限量下载后仅在内存解析，代码仓库与生成产物保存到独立工作区。
- [x] 制定临时文件、失败产物和历史任务的两阶段清理策略。

## 当前状态

M0-M8 的 Module Agent MVP 路线已经完成。独立 Code Worker/GPU 队列、
本地工作区两阶段清理，以及 RabbitMQ/LLM token 的 Prometheus/Grafana
监控也已补齐。当前明确延期的是多用户任务归属与数据隔离。PDF 采用受限的
内存解析，不长期归档；项目也不会自动下载大模型权重。需要长期归档时再把现有
存储端口接到 S3/MinIO，不影响当前工作流。
