from typing import Any

import httpx

from module_agent.shared.config import app_settings
from module_agent.literature.domain.search import PaperSearchResult, SearchRequest
from module_agent.literature.domain.normalization import normalize_doi


OPENALEX_WORKS_URL = "https://api.openalex.org/works"
OPENALEX_FIELDS = ",".join(
    [
        "id",
        "doi",
        "title",
        "publication_year",
        "publication_date",
        "type",
        "authorships",
        "primary_location",
        "best_oa_location",
        "open_access",
        "abstract_inverted_index",
        "cited_by_count",
    ]
)


def rebuild_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    """根据 OpenAlex 倒排索引还原摘要。"""
    if not inverted_index:
        return None

    positioned_words = [
        (position, word)
        for word, positions in inverted_index.items()
        for position in positions
    ]
    positioned_words.sort(key=lambda item: item[0])
    return " ".join(word for _, word in positioned_words)


def parse_work(work: dict[str, Any]) -> PaperSearchResult:
    """解析输入并返回结构化结果。"""
    authors = [
        name
        for authorship in work.get("authorships", [])
        if (name := (authorship.get("author") or {}).get("display_name"))
    ]
    primary_location = work.get("primary_location") or {}
    best_oa_location = work.get("best_oa_location") or {}
    venue_source = primary_location.get("source") or {}
    open_access = work.get("open_access") or {}

    return PaperSearchResult(
        source="openalex",
        source_id=work["id"],
        title=work.get("title") or "Untitled",
        authors=authors,
        publication_year=work.get("publication_year"),
        publication_date=work.get("publication_date"),
        publication_type=work.get("type"),
        venue=venue_source.get("display_name"),
        doi=normalize_doi(work.get("doi")),
        abstract=rebuild_abstract(work.get("abstract_inverted_index")),
        landing_page_url=(
            primary_location.get("landing_page_url")
            or best_oa_location.get("landing_page_url")
        ),
        pdf_url=(
            best_oa_location.get("pdf_url") or primary_location.get("pdf_url")
        ),
        is_open_access=open_access.get("is_oa", False),
        open_access_status=open_access.get("oa_status"),
        cited_by_count=work.get("cited_by_count", 0),
    )


async def search_openalex(query: SearchRequest) -> list[PaperSearchResult]:
    """搜索符合条件的结果。"""
    params = {
        "search": query.topic,
        "filter": (
            f"from_publication_date:{query.start_date},"
            f"to_publication_date:{query.end_date}"
        ),
        "per_page": query.max_results,
        "select": OPENALEX_FIELDS,
    }
    if app_settings.openalex_api_key:
        params["api_key"] = app_settings.openalex_api_key

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(OPENALEX_WORKS_URL, params=params)
        response.raise_for_status()

    return [parse_work(work) for work in response.json().get("results", [])]
