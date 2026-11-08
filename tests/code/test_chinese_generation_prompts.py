"""User-facing prose is Chinese, without translating code or source evidence."""

import pytest

from module_agent.code.adapters.qwen_reproduction import SYSTEM_PROMPT as PLAN_PROMPT
from module_agent.code.adapters.qwen_implementation import SYSTEM_PROMPT as CODE_PROMPT
from module_agent.literature.adapters.llm.qwen_relevance import SYSTEM_PROMPT as RELEVANCE_PROMPT
from module_agent.literature.adapters.llm.qwen_method_extractor import SYSTEM_PROMPT as METHOD_PROMPT
from module_agent.literature.adapters.llm.qwen_query_planner import SYSTEM_PROMPT as QUERY_PROMPT


@pytest.mark.parametrize("prompt", [PLAN_PROMPT, CODE_PROMPT, RELEVANCE_PROMPT, METHOD_PROMPT])
def test_user_explanations_request_simplified_chinese(prompt):
    assert "Simplified Chinese" in prompt


def test_code_dependencies_and_original_evidence_are_not_translated():
    assert "dependency specifiers unchanged" in CODE_PROMPT
    assert "evidence excerpts exactly as supplied, without translation" in METHOD_PROMPT
    assert "English search queries" in QUERY_PROMPT
