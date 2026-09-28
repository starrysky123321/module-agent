from module_agent.shared.llm.qwen_client import QwenClientManager
from module_agent.literature.domain.query import LiteratureQueryPlanner
from module_agent.literature.adapters.llm.qwen_query_planner import QwenLiteratureQueryPlanner
from module_agent.literature.application.query_planning import RuleBasedLiteratureQueryPlanner
from module_agent.literature.application.query_planning import FallbackLiteratureQueryPlanner


def build_literature_query_planner(
    mode: str,
    qwen_model: str,
    qwen_client_manager: QwenClientManager,
    timeout_seconds: float = 180.0,
) -> LiteratureQueryPlanner:
    """构建并返回目标对象。"""
    fallback = RuleBasedLiteratureQueryPlanner()
    
    if mode == "rule":
        return fallback
    elif mode == "qwen":
        primary = QwenLiteratureQueryPlanner(
        client=qwen_client_manager.get_client(),
        model=qwen_model,
    )

        return FallbackLiteratureQueryPlanner(
            primary=primary,
            fallback=fallback,
            timeout_seconds=timeout_seconds,
            model=qwen_model,
        )
    else:
        raise ValueError(f"Unsupported literature query planner mode: {mode}")

    

    
