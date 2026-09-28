"""Task-local capture of token usage returned by OpenAI-compatible clients."""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class LlmTokenUsage:
    """Provider-reported token counts for one completion."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


_latest_usage: ContextVar[LlmTokenUsage | None] = ContextVar(
    "latest_llm_token_usage", default=None
)


def clear_llm_token_usage() -> None:
    """Remove stale usage before starting a new model call."""
    _latest_usage.set(None)


def capture_completion_usage(completion: Any) -> LlmTokenUsage:
    """Capture usage from an OpenAI-compatible completion object."""
    raw = getattr(completion, "usage", None)
    usage = LlmTokenUsage(
        prompt_tokens=max(0, int(getattr(raw, "prompt_tokens", 0) or 0)),
        completion_tokens=max(
            0, int(getattr(raw, "completion_tokens", 0) or 0)
        ),
        total_tokens=max(0, int(getattr(raw, "total_tokens", 0) or 0)),
    )
    _latest_usage.set(usage)
    return usage


def consume_llm_token_usage() -> LlmTokenUsage:
    """Return and clear usage belonging to the current async task."""
    usage = _latest_usage.get() or LlmTokenUsage()
    _latest_usage.set(None)
    return usage
