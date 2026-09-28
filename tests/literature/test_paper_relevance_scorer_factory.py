from unittest.mock import MagicMock

import pytest
from openai import AsyncOpenAI

from module_agent.bootstrap.factories.relevance_scorer import (
    build_paper_relevance_scorer,
)
from module_agent.shared.llm.qwen_client import QwenClientManager
from module_agent.literature.adapters.llm.qwen_relevance import (
    QwenPaperRelevanceScorer,
)
from module_agent.literature.application.relevance import (
    FallbackPaperRelevanceScorer,
    RuleBasedPaperRelevanceScorer,
    ShortlistingPaperRelevanceScorer,
)


def qwen_manager() -> MagicMock:
    client = MagicMock(spec=AsyncOpenAI)
    manager = MagicMock(spec=QwenClientManager)
    manager.get_client.return_value = client
    return manager


def test_factory_builds_rule_scorer_without_qwen_client() -> None:
    manager = qwen_manager()

    scorer = build_paper_relevance_scorer(
        mode="rule",
        qwen_model="qwen3.7-plus",
        qwen_client_manager=manager,
    )

    assert isinstance(scorer, RuleBasedPaperRelevanceScorer)
    manager.get_client.assert_not_called()


def test_factory_builds_shortlisted_qwen_scorer_with_rule_fallback() -> None:
    manager = qwen_manager()

    scorer = build_paper_relevance_scorer(
        mode="qwen",
        qwen_model="qwen3.7-plus",
        qwen_client_manager=manager,
    )

    assert isinstance(scorer, ShortlistingPaperRelevanceScorer)
    assert isinstance(scorer.prefilter_scorer, RuleBasedPaperRelevanceScorer)
    fallback = scorer.shortlist_scorer
    assert isinstance(fallback, FallbackPaperRelevanceScorer)
    assert isinstance(fallback.primary, QwenPaperRelevanceScorer)
    assert fallback.primary.client is manager.get_client.return_value
    assert fallback.primary.model == "qwen3.7-plus"
    assert fallback.fallback is scorer.prefilter_scorer
    manager.get_client.assert_called_once_with()


def test_factory_rejects_unsupported_mode() -> None:
    manager = qwen_manager()

    with pytest.raises(ValueError, match="Unsupported.*invalid"):
        build_paper_relevance_scorer(
            mode="invalid",
            qwen_model="qwen3.7-plus",
            qwen_client_manager=manager,
        )

    manager.get_client.assert_not_called()
