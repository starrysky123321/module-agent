import time

from module_agent.shared.logging import logger
from module_agent.literature.domain.llm_metric import (
    LlmCallMetric,
    LlmCallOutcome,
    LlmCallStage,
)
from module_agent.shared.llm.usage import consume_llm_token_usage
from module_agent.shared.metrics import observe_llm_call


def validate_timeout_seconds(timeout_seconds: float | None) -> None:
    """校验输入和业务约束。"""
    if timeout_seconds is not None and timeout_seconds <= 0:
        raise ValueError("LLM call timeout must be greater than zero")


def record_llm_call(
    *,
    stage: LlmCallStage,
    model: str,
    item_count: int,
    started_at: float,
    timeout_seconds: float,
    outcome: LlmCallOutcome,
    error_type: str | None = None,
) -> LlmCallMetric:
    """记录本次观察结果。"""
    usage = consume_llm_token_usage()
    duration_ms = max(0.0, (time.perf_counter() - started_at) * 1000)
    metric = LlmCallMetric(
        stage=stage,
        model=model,
        item_count=item_count,
        duration_ms=duration_ms,
        timeout_seconds=timeout_seconds,
        outcome=outcome,
        error_type=error_type,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
    )
    observe_llm_call(
        stage=stage,
        model=model,
        outcome=outcome.value,
        duration_seconds=duration_ms / 1000,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
    )
    logger.info(
        "LLM call stage={} model={} items={} outcome={} duration_ms={:.1f} "
        "timeout_s={} error_type={}",
        metric.stage,
        metric.model,
        metric.item_count,
        metric.outcome.value,
        metric.duration_ms,
        metric.timeout_seconds,
        metric.error_type or "-",
    )
    return metric
