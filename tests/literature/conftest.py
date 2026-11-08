"""Capture application diagnostics without depending on stderr sink lifetimes."""

from collections.abc import Iterator

import pytest

from module_agent.shared.logging import logger


@pytest.fixture
def method_logs() -> Iterator[list[str]]:
    messages: list[str] = []
    sink = logger.add(messages.append, format="{message}", level="WARNING")
    try:
        yield messages
    finally:
        logger.remove(sink)
