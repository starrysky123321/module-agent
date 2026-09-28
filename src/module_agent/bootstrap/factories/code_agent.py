from pathlib import Path

import httpx

from module_agent.code.adapters.git import GitRepositoryFetcher
from module_agent.code.adapters.github import GitHubRepositorySearcher
from module_agent.code.adapters.qwen_implementation import (
    QwenReproductionCodeGenerator,
)
from module_agent.code.adapters.qwen_reproduction import QwenReproductionPlanner
from module_agent.code.adapters.repository_analysis import LocalRepositoryAnalyzer
from module_agent.code.adapters.reproduction import LocalReproductionBuilder
from module_agent.code.adapters.workspace import LocalCodeWorkspace
from module_agent.code.application.agent import CodeAgent
from module_agent.shared.llm.qwen_client import QwenClientManager


def build_code_agent(
        *,
        github_client: httpx.AsyncClient,
        qwen_client_manager: QwenClientManager,
        qwen_model: str,
        workspace_root: Path,
        github_token: str = "",
        github_api_version: str = "2022-11-28",
        git_timeout_seconds: float = 120.0,
        confidence_threshold: float = 0.7,
        search_limit: int = 10,
        pdf_max_bytes: int = 25 * 1024 * 1024,
        pdf_timeout_seconds: float = 30.0,
        pdf_parse_timeout_seconds: float = 15.0,
        pdf_max_pages: int = 200,
        pdf_parse_memory_bytes: int = 512 * 1024 * 1024,
        landing_page_max_bytes: int = 2 * 1024 * 1024,
    ) -> CodeAgent:
    """组装 Code Agent 的外部适配器和应用服务。"""
    searcher = GitHubRepositorySearcher(
        github_client,
        token=github_token,
        api_version=github_api_version,
        pdf_max_bytes=pdf_max_bytes,
        pdf_timeout_seconds=pdf_timeout_seconds,
        pdf_parse_timeout_seconds=pdf_parse_timeout_seconds,
        pdf_max_pages=pdf_max_pages,
        pdf_parse_memory_bytes=pdf_parse_memory_bytes,
        landing_page_max_bytes=landing_page_max_bytes,
    )
    
    fetcher = GitRepositoryFetcher(
        timeout_seconds=git_timeout_seconds,
    )
    
    qwen_client = qwen_client_manager.get_client()
    planner = QwenReproductionPlanner(
        client=qwen_client,
        model=qwen_model,
    )
    
    workspace = LocalCodeWorkspace(
        root=workspace_root,
    )
    
    return CodeAgent(
        searcher=searcher,
        fetcher=fetcher,
        planner=planner,
        workspace=workspace,
        analyzer=LocalRepositoryAnalyzer(),
        reproduction_builder=LocalReproductionBuilder(),
        reproduction_code_generator=QwenReproductionCodeGenerator(
            client=qwen_client,
            model=qwen_model,
        ),
        confidence_threshold=confidence_threshold,
        search_limit=search_limit,
    )
    
