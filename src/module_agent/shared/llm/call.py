"""Task-local model timing, provider usage and a cancellation-aware deadline."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import math
import time
from typing import Literal
from module_agent.shared.llm.metric import ModelCallMetric

from module_agent.shared.llm.usage import LlmTokenUsage, clear_llm_token_usage
from module_agent.shared.logging import logger
from module_agent.shared.metrics import observe_llm_call


@dataclass
class ModelCallUsage:
    usage: LlmTokenUsage | None = None


_calls: ContextVar[list[ModelCallMetric] | None] = ContextVar(
    "model_call_metrics", default=None
)


@contextmanager
def capture_model_calls() -> Iterator[list[ModelCallMetric]]:
    """每篇论文独立收集真实指标，不把并发论文的用量混在一起。"""
    calls: list[ModelCallMetric] = []
    token = _calls.set(calls)
    try:
        yield calls
    finally:
        _calls.reset(token)


def validate_model_timeout(value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Model call timeout must be finite and positive")


@asynccontextmanager
async def observed_model_call(
    *, stage: str, model: str, timeout_seconds: float
) -> AsyncIterator[ModelCallUsage]:
    """记录开始/结束，调用、重试和结果校验均纳入同一超时边界。"""
    validate_model_timeout(timeout_seconds)
    started = time.perf_counter()
    outcome: Literal["success", "failed", "timeout", "cancelled"] = "success"
    error_type = None
    call = ModelCallUsage()
    clear_llm_token_usage()
    logger.info(
        "Code model call started | stage={} model={} timeout_s={}",
        stage,
        model,
        timeout_seconds,
    )
    try:
        async with asyncio.timeout(timeout_seconds):
            yield call
    except TimeoutError as error:
        outcome, error_type = "timeout", type(error).__name__
        raise TimeoutError(
            f"代码模型调用 {stage} 超过 {timeout_seconds:g} 秒，已停止等待。"
        ) from error
    except asyncio.CancelledError:
        outcome, error_type = "cancelled", "CancelledError"
        raise
    except Exception as error:
        outcome, error_type = "failed", type(error).__name__
        raise
    finally:
        usage = call.usage
        duration = time.perf_counter() - started
        metric = ModelCallMetric(
            stage=stage,
            model=model,
            outcome=outcome,
            duration_ms=duration * 1000,
            timeout_seconds=timeout_seconds,
            error_type=error_type,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
        )
        calls = _calls.get()
        if calls is not None:
            calls.append(metric)
        observe_llm_call(
            stage=stage,
            model=model,
            outcome=outcome,
            duration_seconds=duration,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )
        logger.info(
            "Code model call finished | stage={} model={} outcome={} duration_ms={:.1f} error_type={}",
            stage,
            model,
            outcome,
            duration * 1000,
            error_type or "-",
        )
