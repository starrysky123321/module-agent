"""Run on the GPU/Docker host, never inside the public API container."""

import argparse
import asyncio
from pathlib import Path

from module_agent.bootstrap import database_models  # noqa: F401
from module_agent.experiments.worker import ExperimentWorker
from module_agent.shared.database.session import async_session_factory, database_engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("workspaces/experiments"))
    parser.add_argument("--cached-image", default="", help="可选：已审核、缓存的不可变 sha256 镜像 ID；不接受标签")
    arguments = parser.parse_args()

    async def run() -> None:
        try:
            await ExperimentWorker(async_session_factory, arguments.workspace, arguments.cached_image).run()
        finally:
            await database_engine.dispose()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("实验 Worker 已停止。")


if __name__ == "__main__":
    main()
