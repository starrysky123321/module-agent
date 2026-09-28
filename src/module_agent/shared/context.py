from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any


request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default="system")
trace_id_ctx_var: ContextVar[str] = ContextVar("trace_id", default="-")
workflow_id_ctx_var: ContextVar[str] = ContextVar(
    "workflow_id",
    default="-",
)
agent_run_id_ctx_var: ContextVar[str] = ContextVar(
    "agent_run_id",
    default="-",
)
message_id_ctx_var: ContextVar[str] = ContextVar(
    "message_id",
    default="-",
)


@contextmanager
def observability_context(
    *,
    request_id: Any | None = None,
    trace_id: Any | None = None,
    workflow_id: Any | None = None,
    agent_run_id: Any | None = None,
    message_id: Any | None = None,
) -> Iterator[None]:
    """Temporarily bind correlation identifiers to the current async task."""

    bindings = (
        (request_id_ctx_var, request_id),
        (trace_id_ctx_var, trace_id),
        (workflow_id_ctx_var, workflow_id),
        (agent_run_id_ctx_var, agent_run_id),
        (message_id_ctx_var, message_id),
    )
    tokens = []
    try:
        for variable, value in bindings:
            if value is not None:
                tokens.append((variable, variable.set(str(value))))
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)
