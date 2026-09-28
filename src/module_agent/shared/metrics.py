"""Prometheus metrics shared by API processes and workers."""

from prometheus_client import Counter, Histogram


HTTP_REQUESTS = Counter(
    "module_agent_http_requests_total",
    "HTTP requests handled by the API.",
    ("method", "route", "status"),
)
HTTP_REQUEST_DURATION = Histogram(
    "module_agent_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "route"),
)
LLM_CALLS = Counter(
    "module_agent_llm_calls_total",
    "LLM calls made by processing stage.",
    ("stage", "model", "outcome"),
)
LLM_CALL_DURATION = Histogram(
    "module_agent_llm_call_duration_seconds",
    "LLM call duration in seconds.",
    ("stage", "model", "outcome"),
)
LLM_TOKENS = Counter(
    "module_agent_llm_tokens_total",
    "Tokens reported by the LLM provider.",
    ("stage", "model", "token_type"),
)
QUEUE_JOBS = Counter(
    "module_agent_queue_jobs_total",
    "Jobs processed by application workers.",
    ("queue", "outcome"),
)


def observe_http_request(
    *, method: str, route: str, status: int, duration_seconds: float
) -> None:
    """Record one bounded-cardinality HTTP observation."""
    HTTP_REQUESTS.labels(method=method, route=route, status=str(status)).inc()
    HTTP_REQUEST_DURATION.labels(method=method, route=route).observe(
        duration_seconds
    )


def observe_llm_call(
    *,
    stage: str,
    model: str,
    outcome: str,
    duration_seconds: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    """Record one model call and the provider-reported token usage."""
    LLM_CALLS.labels(stage=stage, model=model, outcome=outcome).inc()
    LLM_CALL_DURATION.labels(
        stage=stage, model=model, outcome=outcome
    ).observe(duration_seconds)
    if prompt_tokens:
        LLM_TOKENS.labels(
            stage=stage, model=model, token_type="prompt"
        ).inc(prompt_tokens)
    if completion_tokens:
        LLM_TOKENS.labels(
            stage=stage, model=model, token_type="completion"
        ).inc(completion_tokens)
