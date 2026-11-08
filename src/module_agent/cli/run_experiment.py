"""Operator-side experiment CLI; no implicit installs, downloads or API socket access."""

import argparse
import asyncio
import os
from pathlib import Path

from module_agent.experiments.domain import (
    ExperimentBudget,
    ExperimentConsent,
    ExperimentPlan,
    ExperimentResult,
    ExperimentStatus,
)
from module_agent.experiments.docker import DockerExperimentRunner
from module_agent.experiments.mnist import build_m5_plan
from module_agent.experiments.service import ExperimentService
from module_agent.experiments.workspace import ExperimentWorkspace, bounded_read


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(
        description="显式授权的 M5 短程实验；不会自动下载数据或安装依赖。"
    )
    sub = cli.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="核对已经准备的代码和数据，保存冻结计划；不训练")
    plan.add_argument("--workspace-root", type=Path, required=True)
    plan.add_argument("--repository", type=Path, required=True)
    plan.add_argument(
        "--dataset", type=Path, required=True, help="包含 MNIST/raw 的目录"
    )
    plan.add_argument(
        "--image", required=True, help="本机已经构建的 sha256:ID 或 name@sha256:digest"
    )
    plan.add_argument("--gpu-uuid", required=True)
    plan.add_argument(
        "--patch-note", required=True, help="人工审查的兼容补丁说明，内容指纹同时冻结"
    )
    plan.add_argument("--cpu", type=float, default=2)
    plan.add_argument("--memory-mb", type=int, default=4096)
    plan.add_argument("--output-mb", type=int, default=2048)
    plan.add_argument("--timeout-seconds", type=int, default=900)
    plan.add_argument("--output", type=Path, required=True)
    run = sub.add_parser(
        "run", help="在独立受控容器中执行计划；Ctrl+C 停止并保留已有结果"
    )
    run.add_argument("--workspace-root", type=Path, required=True)
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--approve-sha256", required=True)
    run.add_argument("--execute-code", action="store_true", required=True)
    run.add_argument("--acknowledge-source-license", action="store_true", required=True)
    run.add_argument(
        "--acknowledge-gpu-not-memory-capped", action="store_true", required=True
    )
    status = sub.add_parser("status", help="读取持久化实验阶段和结果；不执行代码")
    status.add_argument("--workspace-root", type=Path, required=True)
    status.add_argument("--plan", type=Path, required=True)
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        workspace = ExperimentWorkspace(args.workspace_root)
        if args.command == "plan":
            plan = build_m5_plan(
                workspace,
                repository=args.repository,
                dataset=args.dataset,
                image=args.image,
                budget=ExperimentBudget(
                    cpu_limit=args.cpu,
                    memory_mb=args.memory_mb,
                    output_mb=args.output_mb,
                    timeout_seconds=args.timeout_seconds,
                    gpu_uuid=args.gpu_uuid,
                ),
                patch_note=args.patch_note,
            )
            fd = os.open(
                args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(plan.model_dump_json(indent=2))
            print("计划已保存，尚未执行。授权指纹：" + plan.digest())
            return 0
        plan = ExperimentPlan.model_validate_json(bounded_read(args.plan, 65536))
        if args.command == "status":
            result = ExperimentResult.model_validate_json(
                bounded_read(workspace.run_directory(plan) / "result.json", 2_000_000)
            )
        else:
            consent = ExperimentConsent(
                plan_sha256=args.approve_sha256,
                execute_code=args.execute_code,
                acknowledge_source_license=args.acknowledge_source_license,
                acknowledge_gpu_not_memory_capped=args.acknowledge_gpu_not_memory_capped,
            )
            result = asyncio.run(
                ExperimentService(workspace, DockerExperimentRunner(workspace)).execute(
                    plan, consent
                )
            )
        print(result.model_dump_json(indent=2))
        return 0 if result.status is ExperimentStatus.COMPLETED else 2
    except KeyboardInterrupt:
        print(
            "已停止本机执行并请求清理沙箱；使用 status 查看保留结果，运行机异常时请核对容器状态。"
        )
        return 130
    except Exception as error:
        print("实验未启动或执行失败：" + (str(error).strip() or type(error).__name__))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
