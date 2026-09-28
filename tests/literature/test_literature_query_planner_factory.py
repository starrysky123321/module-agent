from unittest.mock import MagicMock

import pytest
from openai import AsyncOpenAI

from module_agent.bootstrap.factories.query_planner import (
    build_literature_query_planner,
)
from module_agent.shared.llm.qwen_client import QwenClientManager
from module_agent.literature.adapters.llm.qwen_query_planner import (
    QwenLiteratureQueryPlanner,
)
from module_agent.literature.application.query_planning import (
    FallbackLiteratureQueryPlanner,
    RuleBasedLiteratureQueryPlanner,
)


def test_query_planner_factory_builds_rule_planner_without_qwen_client() -> None:
    manager = MagicMock(spec=QwenClientManager)

    planner = build_literature_query_planner(
        mode="rule",
        qwen_model="qwen3.7-plus",
        qwen_client_manager=manager,
    )

    assert isinstance(planner, RuleBasedLiteratureQueryPlanner)
    manager.get_client.assert_not_called()


def test_query_planner_factory_builds_qwen_with_rule_fallback() -> None:
    client = MagicMock(spec=AsyncOpenAI)
    manager = MagicMock(spec=QwenClientManager)
    manager.get_client.return_value = client

    planner = build_literature_query_planner(
        mode="qwen",
        qwen_model="qwen3.7-plus",
        qwen_client_manager=manager,
    )

    assert isinstance(planner, FallbackLiteratureQueryPlanner)
    assert isinstance(planner.primary, QwenLiteratureQueryPlanner)
    assert planner.primary.client is client
    assert planner.primary.model == "qwen3.7-plus"
    assert isinstance(planner.fallback, RuleBasedLiteratureQueryPlanner)
    manager.get_client.assert_called_once_with()


def test_query_planner_factory_rejects_unsupported_mode() -> None:
    manager = MagicMock(spec=QwenClientManager)

    with pytest.raises(ValueError, match="Unsupported literature query planner"):
        build_literature_query_planner(
            mode="unknown",
            qwen_model="qwen3.7-plus",
            qwen_client_manager=manager,
        )

    manager.get_client.assert_not_called()
