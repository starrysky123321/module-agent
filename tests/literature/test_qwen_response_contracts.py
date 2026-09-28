from module_agent.literature.adapters.llm.qwen_query_planner import (
    QwenQueryPlanResponse,
)
from module_agent.literature.adapters.llm.qwen_relevance import (
    QwenRelevanceResponse,
)
from module_agent.literature.adapters.llm.qwen_method_extractor import (
    QwenMethodResponse,
)


def test_qwen_response_schemas_exclude_runtime_metrics() -> None:
    for schema in (
        QwenQueryPlanResponse,
        QwenRelevanceResponse,
        QwenMethodResponse,
    ):
        assert "llm_metrics" not in schema.model_fields
