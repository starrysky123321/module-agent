# Code Agent 两天开发计划

目标：用户确认论文后，Code Agent 能发现并验证候选代码仓库；可信仓库被安全获取并固定 commit；没有可信仓库时生成明确标记的结构化复现计划。第一版绝不自动执行第三方代码。

## 实施表

| 天数 | 顺序 | 工作项 | 主要输出 | 验收标准 | 状态 |
|---|---:|---|---|---|---|
| 第一天 | 1 | 修正模块边界 | `code/domain` 拥有 Code 请求和产物契约 | Workflow 不再定义 `CodeAgentRequest`、`CodeArtifact` | 已完成 |
| 第一天 | 2 | 修正 Agent 输入 | `literature_run_id + papers + code_requirements` | 请求不再依赖未进入 Workflow State 的 `LiteratureBundle` | 已完成 |
| 第一天 | 3 | 定义仓库领域模型 | 候选仓库、来源、证据、可信度 | 非法 URL、可信度和空字段被拒绝 | 已完成 |
| 第一天 | 4 | 定义获取结果和复现计划 | `CodeArtifact`、`RepositoryCheckout`、`ReproductionPlan` | 不完整的 ready/failed/plan 状态被拒绝 | 已完成 |
| 第一天 | 5 | 定义外部端口 | `RepositorySearcher`、`RepositoryFetcher` | 可用 Fake Adapter 独立测试应用层 | 已完成 |
| 第一天 | 6 | 实现候选仓库评分 | 确定性评分和证据合并服务 | DOI、标题、引用、作者证据可解释且结果稳定 | 已完成 |
| 第一天 | 7 | 接入 GitHub 搜索 | GitHub Adapter、README 和仓库元数据读取 | Mock HTTP 覆盖成功、限流、空结果和异常 | 已完成 |
| 第二天 | 1 | 安全获取可信仓库 | Git Adapter、受控 workspace、commit SHA | 不执行安装脚本；路径不能逃逸工作区 | 已完成 |
| 第二天 | 2 | 生成复现计划 | 基于论文画像和用户要求的结构化计划 | 无仓库时不伪装成已复现代码 | 已完成 |
| 第二天 | 3 | 完成 Code Agent 编排 | discovery → scoring → fetch/plan | 每篇论文独立返回一个 CodeArtifact | 已完成 |
| 第二天 | 4 | 接入 Workflow | load selected papers → code node | 论文选择后进入 `code_ready` | 已完成 |
| 第二天 | 5 | 查询和联调 | CodeArtifact 查询接口、Docker 联调 | 真实请求能从选论文运行到 CodeArtifact | 已完成 |

## 两天版不包含

- 执行仓库内的安装脚本或训练脚本。
- 自动下载大型数据集和模型权重。
- 对任意论文自动生成完整且正确的实现。
- 独立 CodeRun RabbitMQ 生命周期。
- GPU 调度和 Validation 沙箱。

这些能力在 Code Agent MVP 跑通后继续迭代。

## MVP 后增强（2026-09-27）

- 已支持从论文 PDF、落地页和补充材料页面发现 GitHub 仓库。
- PDF 下载具有公网地址检查、逐跳重定向检查、超时和大小限制。
- 已支持静态识别依赖清单、入口、模块候选、数据集和模型权重提示。
- 代码状态区分 `open_source`、`source_available`、`not_found` 和 `unknown`。
- 无可信仓库时生成隔离的最小工程骨架；骨架不代表论文方法已经正确复现。
