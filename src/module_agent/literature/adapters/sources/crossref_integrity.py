"""有短超时边界的 Crossref 核验，失败不伪装成论文无撤稿。"""

import asyncio
import re
from urllib.parse import quote

import httpx

from module_agent.literature.domain.integrity import (
    PaperIntegrity,
    PaperIntegrityStatus,
    merge_integrity,
    title_integrity,
)
from module_agent.literature.domain.normalization import normalize_doi


class CrossrefPaperIntegrityChecker:
    def __init__(
        self, client: httpx.AsyncClient, *, timeout_seconds: float = 4.0
    ) -> None:
        self.client = client
        if timeout_seconds <= 0:
            raise ValueError("Integrity timeout must be positive")
        self.timeout_seconds = timeout_seconds

    async def check(self, doi: str | None, title: str) -> PaperIntegrity:
        normalized = normalize_doi(doi)
        unknown = PaperIntegrity(sources=["crossref"])
        if not normalized or not re.fullmatch(
            r"10\.\d{4,9}/\S{1,400}", normalized, re.I
        ):
            return unknown.model_copy(update={"warnings": ["缺少可核验的 DOI"]})
        # arXiv DOI 不属于 Crossref；不能把注册机构不同造成的 404 判作 DOI 无效。
        if normalized.casefold().startswith("10.48550/arxiv."):
            return unknown.model_copy(
                update={"warnings": ["arXiv DOI 未在 Crossref 核验"]}
            )
        url = "https://api.crossref.org/works/" + quote(normalized, safe="")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                response = await self.client.get(
                    url, timeout=self.timeout_seconds, follow_redirects=False
                )
                response.raise_for_status()
                message = response.json()["message"]
                returned_doi = normalize_doi(message.get("DOI"))
                if not returned_doi or returned_doi.casefold() != normalized.casefold():
                    raise ValueError("Crossref DOI does not match request")
                titles = message.get("title")
                if not isinstance(titles, list) or not any(
                    isinstance(item, str) and item.strip() for item in titles
                ):
                    raise ValueError("Crossref record has no title")
                facts = [
                    title_integrity(item, "crossref")
                    for item in titles
                    if isinstance(item, str)
                ]
                # update-to 的 DOI 是被更新的工作：当前文档是声明，不应当作原论文推荐。
                if any(
                    isinstance(update, dict) and update.get("type") == "retraction"
                    for update in (message.get("update-to") or [])
                ):
                    facts.append(
                        PaperIntegrity(
                            status=PaperIntegrityStatus.NOTICE,
                            sources=["crossref"],
                            evidence=[f"Crossref retraction update-to: {normalized}"],
                        )
                    )
                return merge_integrity(
                    PaperIntegrity(
                        status=PaperIntegrityStatus.NOT_FLAGGED,
                        sources=["crossref"],
                        evidence=[f"Crossref DOI: {normalized}"],
                    ),
                    *facts,
                )
        except (
            httpx.HTTPError,
            TimeoutError,
            ValueError,
            KeyError,
            TypeError,
        ) as error:
            return unknown.model_copy(
                update={
                    "warnings": [
                        f"Crossref 未能核验（{type(error).__name__}），不能据此认定无撤稿"
                    ]
                }
            )
