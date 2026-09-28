import asyncio
import httpx
from typing import Any

from module_agent.literature.domain.search import PaperSearchResult
from module_agent.literature.domain.normalization import normalize_doi
from module_agent.literature.domain.search import SearchRequest
from module_agent.shared.config import app_settings
from module_agent.shared.exceptions import LiteratureSourceSkippedError
from datetime import date
from module_agent.shared.http.rate_limiter import AsyncRateLimiter
from module_agent.shared.http.retry import (
    RETRYABLE_STATUS_CODES,
    AsyncHttpRetry,
)
from module_agent.shared.http.circuit_breaker import (
    AsyncCircuitBreaker,
    CircuitOpenError,
)

semantic_scholar_rate_limiter = AsyncRateLimiter(
    min_interval_seconds=1.2
)

semantic_scholar_http_retry = AsyncHttpRetry(
    max_attempts=4,
    base_delay_seconds=2.0,
)

semantic_scholar_circuit_breaker = AsyncCircuitBreaker(
    failure_threshold=(
        app_settings.semantic_scholar_circuit_failure_threshold
    ),
    recovery_timeout_seconds=(
        app_settings.semantic_scholar_circuit_recovery_seconds
    ),
)



SEMANTIC_SCHOLAR_URL = (
    "https://api.semanticscholar.org/graph/v1/paper/search"
)

SEMANTIC_SCHOLAR_FIELDS = ",".join(
    (
        "paperId",
        "title",
        "authors",
        "year",
        "publicationDate",
        "publicationTypes",
        "venue",
        "externalIds",
        "abstract",
        "url",
        "openAccessPdf",
        "citationCount",
    )
)


def parse_paper(paper: dict[str, Any]) -> PaperSearchResult:
    """解析输入并返回结构化结果。"""
    authors = [
        name
        for author in paper.get("authors") or []
        if (name := author.get("name"))
    ]
    external_ids = paper.get("externalIds") or {}
    open_access_pdf = paper.get("openAccessPdf") or {}
    publication_types = paper.get("publicationTypes") or []
    pdf_url = open_access_pdf.get("url")

    return PaperSearchResult(
        source="semantic_scholar",
        source_id=paper["paperId"],
        title=paper.get("title") or "Untitled",
        authors=authors,
        publication_year=paper.get("year"),
        publication_date=paper.get("publicationDate"),
        publication_type=(
            publication_types[0] if publication_types else None
        ),
        venue=paper.get("venue"),
        doi=normalize_doi(external_ids.get("DOI")),
        abstract=paper.get("abstract"),
        landing_page_url=paper.get("url"),
        pdf_url=pdf_url,
        is_open_access=bool(pdf_url),
        open_access_status=open_access_pdf.get("status"),
        cited_by_count=paper.get("citationCount") or 0,
    )


async def search_semantic_scholar(
    query: SearchRequest,
) -> list[PaperSearchResult]:
    """搜索符合条件的结果。"""
    params = {
        "query": query.topic,
        "limit": min(query.max_results, 100),
        "year": (
            str(query.start_date.year)
            if query.start_date.year == query.end_date.year
            else (
                f"{query.start_date.year}-"
                f"{query.end_date.year}"
            )
        ),
        "fields": SEMANTIC_SCHOLAR_FIELDS,
    }

    headers: dict[str, str] = {}

    if app_settings.semantic_scholar_api_key:
        headers["x-api-key"] = (
            app_settings.semantic_scholar_api_key
        )

    try:
        await semantic_scholar_circuit_breaker.before_call()
    except CircuitOpenError as exc:
        raise LiteratureSourceSkippedError(
            "Semantic Scholar circuit breaker is open"
        ) from exc

    async with httpx.AsyncClient(timeout=30.0) as client:

        async def send_request() -> httpx.Response:
            await semantic_scholar_rate_limiter.wait()
            return await client.get(
                SEMANTIC_SCHOLAR_URL,
                params=params,
                headers=headers,
            )
            
        try:
            response = await semantic_scholar_http_retry.execute(
                send_request,
            )
        except (asyncio.CancelledError, httpx.RequestError):
            await semantic_scholar_circuit_breaker.record_failure()
            raise

        if response.status_code in RETRYABLE_STATUS_CODES:
            await semantic_scholar_circuit_breaker.record_failure()
        else:
            await semantic_scholar_circuit_breaker.record_success()

        response.raise_for_status()

    papers = [
        parse_paper(item)
        for item in response.json().get("data", [])
    ]

    
    return [
            paper
            for paper in papers
            if _is_within_date_range(
                paper=paper,
                start_date=query.start_date,
                end_date=query.end_date,
            )
        ]


def _is_within_date_range(
    paper: PaperSearchResult,
    start_date: date,
    end_date: date,
) -> bool:
    # 有精确发表日期时，严格按日期过滤
    if paper.publication_date is not None:
        return start_date <= paper.publication_date <= end_date

    # 没有精确日期时，退化为按年份判断
    if paper.publication_year is not None:
        return start_date.year <= paper.publication_year <= end_date.year

    # 日期和年份都没有，无法判断是否在范围内
    return False
