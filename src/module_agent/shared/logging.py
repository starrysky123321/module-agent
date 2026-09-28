import sys
from typing import Any

from loguru import logger as loguru_logger

from module_agent.shared.context import (
    agent_run_id_ctx_var,
    message_id_ctx_var,
    request_id_ctx_var,
    trace_id_ctx_var,
    workflow_id_ctx_var,
)


def _inject_context(record: dict[str, Any]) -> None:
    record["extra"]["request_id"] = request_id_ctx_var.get() or "-"
    record["extra"]["trace_id"] = trace_id_ctx_var.get() or "-"
    record["extra"]["workflow_id"] = workflow_id_ctx_var.get() or "-"
    record["extra"]["agent_run_id"] = agent_run_id_ctx_var.get() or "-"
    record["extra"]["message_id"] = message_id_ctx_var.get() or "-"


def _configure_logger():
    loguru_logger.remove()
    patched_logger = loguru_logger.patch(_inject_context)
    patched_logger.add(
        sys.stderr,
        level="INFO",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | "
            "{level:<8} | "
            "request={extra[request_id]} trace={extra[trace_id]} "
            "workflow={extra[workflow_id]} run={extra[agent_run_id]} "
            "message={extra[message_id]} | "
            "{name}:{function}:{line} | "
            "{message}"
        ),
    )
    return patched_logger


logger = _configure_logger()
