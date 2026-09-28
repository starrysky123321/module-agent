from pathlib import Path
from unittest.mock import MagicMock

import httpx
from openai import AsyncOpenAI

from module_agent.bootstrap.factories.code_agent import build_code_agent
from module_agent.code.adapters.git import GitRepositoryFetcher
from module_agent.code.adapters.github import GitHubRepositorySearcher
from module_agent.code.adapters.qwen_reproduction import QwenReproductionPlanner
from module_agent.code.adapters.repository_analysis import LocalRepositoryAnalyzer
from module_agent.code.adapters.reproduction import LocalReproductionBuilder
from module_agent.code.adapters.workspace import LocalCodeWorkspace
from module_agent.code.application.agent import CodeAgent
from module_agent.shared.llm.qwen_client import QwenClientManager


def test_factory_builds_code_agent_with_supplied_dependencies(
    tmp_path: Path,
) -> None:
    github_client = MagicMock(spec=httpx.AsyncClient)
    qwen_client = MagicMock(spec=AsyncOpenAI)
    qwen_manager = MagicMock(spec=QwenClientManager)
    qwen_manager.get_client.return_value = qwen_client

    agent = build_code_agent(
        github_client=github_client,
        github_token="  github-token  ",
        github_api_version="2022-11-28",
        qwen_client_manager=qwen_manager,
        qwen_model="  qwen3.7-plus  ",
        workspace_root=tmp_path / "workspaces",
        git_timeout_seconds=45.0,
        confidence_threshold=0.8,
        search_limit=6,
    )

    assert isinstance(agent, CodeAgent)
    assert isinstance(agent.searcher, GitHubRepositorySearcher)
    assert agent.searcher.client is github_client
    assert agent.searcher.token == "github-token"
    assert agent.searcher.api_version == "2022-11-28"
    assert isinstance(agent.fetcher, GitRepositoryFetcher)
    assert agent.fetcher.timeout_seconds == 45.0
    assert isinstance(agent.planner, QwenReproductionPlanner)
    assert agent.planner.client is qwen_client
    assert agent.planner.model == "qwen3.7-plus"
    assert isinstance(agent.workspace, LocalCodeWorkspace)
    assert isinstance(agent.analyzer, LocalRepositoryAnalyzer)
    assert isinstance(agent.reproduction_builder, LocalReproductionBuilder)
    assert agent.workspace.root == (tmp_path / "workspaces").resolve()
    assert agent.confidence_threshold == 0.8
    assert agent.search_limit == 6
    assert agent.searcher.pdf_max_bytes == 25 * 1024 * 1024
    assert agent.searcher.pdf_timeout_seconds == 30.0
    qwen_manager.get_client.assert_called_once_with()
