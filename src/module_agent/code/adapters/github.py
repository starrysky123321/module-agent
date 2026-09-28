from typing import Any

import httpx
from pypdf.errors import PyPdfError

from module_agent.code.adapters.paper_links import PaperLinkRepositorySearcher
from module_agent.code.adapters.pdf_repository import PdfRepositorySearcher
from module_agent.code.domain.request import CodePaperInput
from module_agent.code.domain.repository import (
    RepositoryCandidate,
    RepositoryEvidence,
    RepositoryEvidenceType,
)
from module_agent.code.domain.errors import PdfDownloadError
from module_agent.shared.logging import logger



class GitHubRepositorySearcher:
    """搜索 GitHub，并加载评分所需的仓库元数据。"""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        token: str = "",
        api_version: str = "2022-11-28",
        pdf_max_bytes: int = 25 * 1024 * 1024,
        pdf_timeout_seconds: float = 30.0,
        landing_page_max_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        """保存 GitHub HTTP 客户端和鉴权配置。"""
        self.client = client
        self.token = token.strip()
        self.api_version = api_version.strip()
        self.pdf_max_bytes = pdf_max_bytes
        self.pdf_timeout_seconds = pdf_timeout_seconds
        self.landing_page_max_bytes = landing_page_max_bytes
        if not self.api_version:
            raise ValueError("GitHub API version cannot be empty")
        if (
            self.pdf_max_bytes <= 0
            or self.pdf_timeout_seconds <= 0
            or self.landing_page_max_bytes <= 0
        ):
            raise ValueError("Repository discovery limits must be positive")

    async def search(
        self,
        paper: CodePaperInput,
        *,
        limit: int = 10,
    ) -> list[RepositoryCandidate]:
        """按论文标题搜索仓库，并为每个候选读取 README。"""
        if not 1 <= limit <= 100:
            raise ValueError("GitHub repository search limit must be between 1 and 100")
                

        response = await self.client.get(
            "/search/repositories",
            params={
                "q": f'"{paper.title}" in:name,description,readme',
                "per_page": limit,
                "sort": "stars",
                "order": "desc",
            },
            headers=self._headers(),
        )
        response.raise_for_status()

        candidates: list[RepositoryCandidate] = []
        for item in response.json().get("items", []):
            candidate = self._parse_candidate(item)
            if candidate is None:
                continue
            readme = await self._get_readme(candidate.full_name)
            candidates.append(
                candidate.model_copy(update={"readme_text": readme})
            )
            
        if paper.pdf_url is not None:
            try:
                repositories = await PdfRepositorySearcher(
                    self.client,
                    max_bytes=self.pdf_max_bytes,
                    timeout_seconds=self.pdf_timeout_seconds,
                ).search_github_links(
                    paper=paper,
                    limit=limit,
                )
            except (httpx.HTTPError, PdfDownloadError, PyPdfError) as exc:
                logger.warning(
                    "PDF repository discovery failed for paper {} ({}): {}",
                    paper.source_id,
                    type(exc).__name__,
                    str(exc),
                )
                repositories = []

            for item in repositories:
                candidate = self._parse_candidate(item)
                if candidate is None:
                    continue
                readme = await self._get_readme(candidate.full_name)
                
                direct_evidence = RepositoryEvidence.model_validate(
                    {
                        "evidence_type": RepositoryEvidenceType.PAPER_URL,
                        "description": (
                            "Repository URL found in paper PDF"
                        ),
                        "weight": 0.95,
                        "source_url": paper.pdf_url,
                    }
                )
                candidates.append(
                    candidate.model_copy(
                        update={
                            "readme_text": readme,
                            "evidence": [
                                *candidate.evidence,
                                direct_evidence,
                            ],
                        }
                    )
                )

        if paper.landing_page_url or paper.supplementary_urls:
            try:
                linked_repositories = await PaperLinkRepositorySearcher(
                    self.client,
                    max_bytes=self.landing_page_max_bytes,
                    timeout_seconds=self.pdf_timeout_seconds,
                ).search_github_links(paper, limit=limit)
            except (httpx.HTTPError, PdfDownloadError) as exc:
                logger.warning(
                    "Paper page repository discovery failed for paper {} "
                    "({}): {}",
                    paper.source_id,
                    type(exc).__name__,
                    str(exc),
                )
                linked_repositories = []

            for item, source_url in linked_repositories:
                candidate = self._parse_candidate(item)
                if candidate is None:
                    continue
                readme = await self._get_readme(candidate.full_name)
                evidence = RepositoryEvidence.model_validate(
                    {
                        "evidence_type": RepositoryEvidenceType.PAPER_URL,
                        "description": (
                            "Repository URL found on a paper or "
                            "supplementary-material page"
                        ),
                        "weight": 0.95,
                        "source_url": source_url,
                    }
                )
                candidates.append(
                    candidate.model_copy(
                        update={
                            "readme_text": readme,
                            "evidence": [*candidate.evidence, evidence],
                        }
                    )
                )

        return self._deduplicate_candidates(candidates)

    @staticmethod
    def _deduplicate_candidates(
        candidates: list[RepositoryCandidate],
    ) -> list[RepositoryCandidate]:
        """按仓库全名去重，并合并不同搜索途径提供的证据。"""
        unique: dict[str, RepositoryCandidate] = {}

        for candidate in candidates:
            key = candidate.full_name.casefold()
            existing = unique.get(key)
            if existing is None:
                unique[key] = candidate
                continue

            evidence = list(existing.evidence)
            for item in candidate.evidence:
                if item not in evidence:
                    evidence.append(item)

            unique[key] = existing.model_copy(
                update={
                    "readme_text": (
                        existing.readme_text or candidate.readme_text
                    ),
                    "evidence": evidence,
                }
            )

        return list(unique.values())

    async def _get_readme(self, full_name: str) -> str | None:
        """读取仓库 README；不存在时返回 None。"""
        response = await self.client.get(
            f"/repos/{full_name}/readme",
            headers={
                **self._headers(),
                "Accept": "application/vnd.github.raw+json",
            },
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.text

    def _headers(self) -> dict[str, str]:
        """构造 GitHub API 版本和可选 Token 请求头。"""
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.api_version,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    @staticmethod
    def _parse_candidate(item: Any) -> RepositoryCandidate | None:
        """把 GitHub API 条目转换为仓库候选。"""
        if not isinstance(item, dict):
            return None

        owner = item.get("owner")
        owner_login = owner.get("login") if isinstance(owner, dict) else None
        full_name = item.get("full_name")
        repository_url = item.get("html_url")
        if not full_name or not repository_url or not owner_login:
            return None

        license_data = item.get("license")
        license_spdx = (
            license_data.get("spdx_id")
            if isinstance(license_data, dict)
            else None
        )

        return RepositoryCandidate(
            provider="github",
            full_name=full_name,
            repository_url=repository_url,
            owner_login=owner_login,
            description=item.get("description"),
            topics=item.get("topics") or [],
            default_branch=item.get("default_branch"),
            archived=bool(item.get("archived", False)),
            license_spdx=(
                license_spdx
                if license_spdx and license_spdx != "NOASSERTION"
                else None
            ),
        )
