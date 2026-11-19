# 连接池耗尽与工作流恢复

2026-11-07 在独立数据库和消息队列上，对一次 20 并发工作流启动超时做了修复复测。源码修复见提交 [`dd6572d`](https://github.com/starrysky123321/module-agent/commit/dd6572d)。

## 故障与修复

- 工作流请求持有业务连接，随后调用会申请其他连接的步骤。并发升高后，长事务占用默认连接池，启动请求等待超时。工作流路径改为短会话和短事务，在调用 LangGraph、发消息或访问其他仓库前释放连接。
- LangGraph Checkpoint 从长期持有单条 psycopg 连接改用 `AsyncConnectionPool`，在借出前检查连接并替换失效连接。readiness 使用实际的 Checkpoint 连接池查询 `checkpoints` 表。
- 默认业务连接池参数在修复前后相同，`pool_size=5`、`max_overflow=10`。

## 隔离复测

| 场景 | 完成 / 调度 | 端到端 P95 |
| --- | ---: | ---: |
| 5 并发 | 10 / 10 | 3.76 秒 |
| 10 并发 | 20 / 20 | 5.42 秒 |
| 20 并发 | 20 / 20 | 9.30 秒 |
| PostgreSQL 恢复后，5 并发 | 5 / 5 | 3.56 秒 |

复测走真实 HTTP、RabbitMQ、PostgreSQL、Redis、LangGraph Checkpoint、代码产物登记和静态验证。每个任务处理 10 条合成论文记录、选择其中 2 篇，论文来源和仓库获取由测试适配器提供。P95 来自单机短批次，API 和 Worker 各配置 1 CPU、512 MiB，外部模型请求关闭。

四个批次共 55 个工作流，生成 110 份代码产物和 110 份静态验证报告。同一任务和 attempt 没有重复 Code Run，同一 Code Run 和论文没有重复产物。

## PostgreSQL 恢复

空闲时停止隔离 PostgreSQL 约 4 秒，API readiness 返回 503。数据库重新启动后，API 和 Worker 保持原进程，readiness 约在探测开始后 6.85 秒恢复 200，随后 5 个新工作流全部完成。

另一次集成测试主动关闭测试自己的闲置 Checkpoint 连接，使用同一个已编译的图读取原 Checkpoint 并恢复流程。停机演练覆盖空闲后的新任务，集成测试覆盖闲置连接失效后的旧断点，两项结果的边界以各自场景为准。

## 如何核对

- [工作台演示](workbench-dropedge.webm)展示独立的 DropEdge 真实验收记录，包含仓库来源证据、固定提交和静态检查。
- [数据库恢复演练脚本](../../scripts/service_recovery_drill.sh)和[验收入口](../../src/module_agent/cli/run_release_acceptance.py)用于启动另一次验证。
- [PostgreSQL Checkpointer 实现](../../src/module_agent/shared/checkpoint/postgres.py)和[恢复集成测试](../../tests/integration/test_postgres_workflow_resume.py)覆盖上述数据库连接行为。
