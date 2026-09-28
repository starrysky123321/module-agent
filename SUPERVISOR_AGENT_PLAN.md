# Supervisor Agent 两天开发计划

目标：让 Supervisor 成为总工作流中真正的状态决策器。它只读取类型化的 `ModuleGraphState`，校验当前状态是否自洽，然后决定进入 Literature、人工选文、Code、Validation 或结束阶段。专业 Agent 仍然只负责自己的业务，不能互相直接调用。

第一版使用确定性规则完成调度，不让 LLM 控制关键状态跳转。LLM 后续只能用于理解复杂要求和生成进度说明，并且必须保留规则回退。

## 输入与输出

输入：

- `ModuleGraphState`
- 当前 `WorkflowStatus`
- 已经产生的论文选择、代码产物、验证报告和技术错误
- 各阶段尝试次数与允许的重试预算

输出：

- `SupervisorDecision`
  - 决策类型：路由、等待、重试、完成或失败
  - `next_step`：下一个专业阶段
  - `status`：决策后的工作流状态
  - `reason`：可供 API 和日志展示的明确原因

最终汇总输出：

- `ModuleBuildResult`
  - Literature Run 与所选论文
  - Code Artifacts
  - Validation Reports
  - 总状态、警告和失败信息

## 实施表

| 天数 | 顺序 | 工作项 | 主要输出 | 验收标准 | 状态 |
|---|---:|---|---|---|---|
| 第一天 | 1 | 定义 Supervisor 领域契约 | `SupervisorDecision`、决策类型和失败信息模型 | 普通字符串不能绕过枚举；非法组合被模型拒绝 | 已完成 |
| 第一天 | 2 | 明确 Workflow 状态语义 | 各状态所需字段与合法后继状态表 | `created → literature → selection → code → validation → finish` 可被静态检查 | 已完成 |
| 第一天 | 3 | 实现状态一致性检查器 | 对 State 中论文、选择、代码和报告的依赖关系做校验 | 未选论文不能出现代码产物；无代码产物不能出现验证报告 | 已完成 |
| 第一天 | 4 | 实现确定性决策策略 | Rule-based `SupervisorAgent.run()` | 任意合法状态都返回唯一、可解释的下一步 | 已完成 |
| 第一天 | 5 | 区分业务结果与技术失败 | 失败分类、是否可重试、终止原因 | Validation 的 failed 报告仍是正常完成；系统异常才使 Workflow failed | 已完成 |
| 第一天 | 6 | 完成 Supervisor 单元测试 | 状态矩阵、非法跳转和失败测试 | 不依赖 LangGraph 即可完整测试决策规则 | 已完成 |
| 第二天 | 1 | 注册 Supervisor 节点 | LangGraph `supervisor` 节点 | START 和各专业阶段完成后都回到 Supervisor | 已完成 |
| 第二天 | 2 | 用条件路由替换固定连线 | SupervisorDecision 驱动条件边 | Workflow 不再由硬编码的 `code → validation → END` 决定流程 | 已完成 |
| 第二天 | 3 | 接入等待与恢复边界 | Literature 等待、论文选择 interrupt/resume | Supervisor 不会绕过人工选择，也不会重复派发已完成阶段 | 已完成 |
| 第二天 | 4 | 接入受限重试和失败终止 | 尝试次数、重试预算和失败状态 | 不产生无限循环；非幂等阶段默认不自动重试 | 已完成 |
| 第二天 | 5 | 汇总最终构建结果 | `ModuleBuildResult` 和结果查询服务 | 最终结果可从 checkpoint 稳定恢复并进行模型校验 | 已完成 |
| 第二天 | 6 | API 与端到端测试 | 状态/结果查询接口和完整 Workflow 测试 | 从文献阶段到最终 ValidationReport 全链路通过 | 已完成 |

## 目标状态转换

| 当前事实 | Supervisor 决策 |
|---|---|
| 新任务，尚未启动文献阶段 | 路由到 Literature |
| Literature 正在异步运行 | 等待 Literature 完成事件 |
| Literature 已完成，尚未选择论文 | 等待人工选择 |
| 已选择论文，尚无 CodeArtifact | 路由到 Code |
| 已有 CodeArtifact，尚无 ValidationReport | 路由到 Validation |
| 已有完整 ValidationReport | 汇总结果并正常完成 |
| 出现不可恢复的技术异常 | 记录失败并终止 |
| 出现可恢复异常且阶段幂等、预算未耗尽 | 有限重试当前阶段 |

## 设计边界

- Supervisor 不搜索论文、不克隆仓库、不执行验证命令。
- 专业 Agent 不直接调用另一个专业 Agent。
- ValidationReport 为 `failed` 表示验证结论，不等于工作流执行异常。
- CodeArtifact 为 `failed` 仍然是 Code Agent 的结构化业务输出，可以继续生成对应验证报告。
- 只有技术异常进入 Workflow `FAILED` 状态。
- 非幂等阶段默认不自动重试，避免重复克隆、重复写库或重复执行代码。
- 所有重试必须有明确上限，并保存尝试次数和最后一次错误。
- LLM 不能跳过人工选文、安全策略或状态一致性检查。

## 两天版不包含

- 让 LLM 自由决定任意工作流节点或执行命令。
- Validation 失败后自动修改代码并形成无限自修复循环。
- 独立的 Supervisor Worker 和消息队列。
- 多用户权限、计费、优先级调度和分布式锁。
- GPU 任务调度、论文训练实验或大型数据集生命周期。

这些能力应在确定性 Supervisor 和全链路状态恢复稳定后继续迭代。

## Jev 决策增强（已完成）

Supervisor 现在提供三种可配置策略：

- `rule`：只执行确定性规则，不创建 Jev 客户端。
- `jev_shadow`：规则继续控制流程，Jev 只提供 retry/stop 建议并持久化观察结果。
- `jev_guarded`：只有当规则准备重试、Jev 给出达到阈值的 stop 建议时，Jev 才能否决重试。Jev 不能把规则的 stop 改成 retry，也不能改变正常节点路由。

已实现的安全与可观测性：

- [x] TypeSafe/Jev 异步客户端生命周期、超时和配置校验。
- [x] Jev 结构化 Choice 输出、概率和置信度校验。
- [x] 调用失败时确定性规则回退。
- [x] Shadow 观察结果独立事务持久化，不污染 Workflow 业务事务。
- [x] 统计成功率、一致率、高置信度分歧率、平均置信度和耗时。
- [x] 按运行、时间范围和失败类别查询观察数据。
- [x] 根据样本量和调用可靠性输出人工评审就绪状态。
- [x] 主动策略保持默认关闭，必须显式设置 `SUPERVISOR_POLICY=jev_guarded`。
