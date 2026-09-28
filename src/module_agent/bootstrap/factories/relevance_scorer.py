from module_agent.literature.domain.ranking import PaperRelevanceScorer
from module_agent.shared.llm.qwen_client import (
    QwenClientManager,
)
from module_agent.literature.adapters.llm.qwen_relevance import (
    QwenPaperRelevanceScorer,
)
from module_agent.literature.application.relevance import (
    FallbackPaperRelevanceScorer,
    RuleBasedPaperRelevanceScorer,
    ShortlistingPaperRelevanceScorer,
)


def build_paper_relevance_scorer(
    mode: str,
    qwen_model: str,
    qwen_client_manager: QwenClientManager,
    timeout_seconds: float = 180.0,
) -> PaperRelevanceScorer:
    """构建并返回目标对象。"""
    rule_scorer = RuleBasedPaperRelevanceScorer()

    if mode == "rule":
        return rule_scorer

    if mode == "qwen":
        qwen_scorer = QwenPaperRelevanceScorer(
            client=qwen_client_manager.get_client(),
            model=qwen_model,
        )

        fallback_scorer = FallbackPaperRelevanceScorer(
            primary=qwen_scorer,
            fallback=rule_scorer,
            timeout_seconds=timeout_seconds,
            model=qwen_model,
        )
        return ShortlistingPaperRelevanceScorer(
            prefilter_scorer=rule_scorer,
            shortlist_scorer=fallback_scorer,
        )

    raise ValueError(
        f"Unsupported paper relevance scorer mode: {mode}"
    )
