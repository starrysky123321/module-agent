from unittest.mock import MagicMock

import pytest
from openai import AsyncOpenAI

from module_agent.bootstrap.factories.method_extractor import (
    build_paper_method_extractor,
)
from module_agent.shared.llm.qwen_client import QwenClientManager
from module_agent.literature.adapters.llm.qwen_method_extractor import (
    QwenPaperMethodExtractor,
)
from module_agent.literature.application.method_extraction import (
    BatchedPaperMethodExtractor,
    FallbackPaperMethodExtractor,
)


def manager() -> MagicMock:
    qwen_client = MagicMock(spec=AsyncOpenAI)
    qwen_manager = MagicMock(spec=QwenClientManager)
    qwen_manager.get_client.return_value = qwen_client
    return qwen_manager


def test_factory_off_mode_returns_none_without_creating_qwen_client() -> None:
    qwen_manager = manager()

    extractor = build_paper_method_extractor(
        mode="off",
        qwen_model="qwen3.7-plus",
        qwen_client_manager=qwen_manager,
    )

    assert extractor is None
    qwen_manager.get_client.assert_not_called()


def test_factory_qwen_mode_builds_batched_fallback_extractor() -> None:
    qwen_manager = manager()

    extractor = build_paper_method_extractor(
        mode="qwen",
        qwen_model="qwen3.7-plus",
        qwen_client_manager=qwen_manager,
    )

    assert isinstance(extractor, BatchedPaperMethodExtractor)
    assert extractor.batch_size == 10
    assert isinstance(extractor.inner, FallbackPaperMethodExtractor)
    assert isinstance(extractor.inner.primary, QwenPaperMethodExtractor)
    assert extractor.inner.primary.client is qwen_manager.get_client.return_value
    assert extractor.inner.primary.model == "qwen3.7-plus"
    qwen_manager.get_client.assert_called_once_with()


def test_factory_rejects_unknown_mode() -> None:
    qwen_manager = manager()

    with pytest.raises(ValueError, match="Unknown mode: invalid"):
        build_paper_method_extractor(
            mode="invalid",
            qwen_model="qwen3.7-plus",
            qwen_client_manager=qwen_manager,
        )

    qwen_manager.get_client.assert_not_called()
