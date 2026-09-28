from typing import Any

import httpx

from module_agent.code.adapters.pdf_repository import (
    download_text,
    extract_github_links,
    get_github_repository,
    parse_github_repo_url,
)
from module_agent.code.domain.request import CodePaperInput


class PaperLinkRepositorySearcher:
    """从论文落地页和补充材料页面发现 GitHub 仓库。"""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        max_bytes: int = 2 * 1024 * 1024,
        timeout_seconds: float = 15.0,
    ) -> None:
        if max_bytes <= 0 or timeout_seconds <= 0:
            raise ValueError("Paper link download limits must be positive")
        self.client = client
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds

    async def search_github_links(
        self,
        paper: CodePaperInput,
        *,
        limit: int = 10,
    ) -> list[tuple[dict[str, Any], str]]:
        """返回仓库元数据及提供该链接的论文页面。"""
        if not 1 <= limit <= 100:
            raise ValueError(
                "Paper link search limit must be between 1 and 100"
            )

        source_urls = list(
            dict.fromkeys(
                url
                for url in (
                    paper.landing_page_url,
                    *paper.supplementary_urls,
                )
                if url
            )
        )
        discovered: list[tuple[str, str]] = []
        for source_url in source_urls:
            if parse_github_repo_url(source_url) is not None:
                discovered.append((source_url, source_url))
                continue
            text = await download_text(
                source_url,
                max_bytes=self.max_bytes,
                timeout_seconds=self.timeout_seconds,
            )
            discovered.extend(
                (repository_url, source_url)
                for repository_url in extract_github_links(text)
            )

        result: list[tuple[dict[str, Any], str]] = []
        seen: set[str] = set()
        for repository_url, source_url in discovered:
            key = repository_url.casefold()
            if key in seen:
                continue
            seen.add(key)
            repository = await get_github_repository(
                self.client,
                repository_url,
            )
            if repository is not None:
                result.append((repository, source_url))
            if len(result) >= limit:
                break
        return result
