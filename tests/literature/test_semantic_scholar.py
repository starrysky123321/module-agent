import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from module_agent.shared.exceptions import LiteratureSourceSkippedError
from module_agent.literature.domain.search import SearchRequest
from module_agent.shared.http.circuit_breaker import CircuitOpenError
from module_agent.literature.adapters.sources.semantic_scholar import (
    SEMANTIC_SCHOLAR_FIELDS,
    SEMANTIC_SCHOLAR_URL,
    parse_paper,
    search_semantic_scholar,
)


def test_parse_semantic_scholar_paper() -> None:
    parsed = parse_paper(
        {
            "paperId": "s2-paper-123",
            "title": "Example Paper",
            "authors": [{"name": "Author One"}, {"name": ""}],
            "year": 2025,
            "publicationDate": "2025-01-15",
            "publicationTypes": ["Conference", "JournalArticle"],
            "venue": "CVPR",
            "externalIds": {
                "DOI": "https://doi.org/10.1000/EXAMPLE",
            },
            "abstract": "Example abstract",
            "url": "https://www.semanticscholar.org/paper/example",
            "openAccessPdf": {
                "url": "https://example.org/paper.pdf",
                "status": "GREEN",
            },
            "citationCount": 42,
        }
    )

    assert parsed.source == "semantic_scholar"
    assert parsed.source_id == "s2-paper-123"
    assert parsed.authors == ["Author One"]
    assert parsed.publication_year == 2025
    assert parsed.publication_date == date(2025, 1, 15)
    assert parsed.publication_type == "Conference"
    assert parsed.venue == "CVPR"
    assert parsed.doi == "10.1000/EXAMPLE"
    assert parsed.landing_page_url == (
        "https://www.semanticscholar.org/paper/example"
    )
    assert parsed.pdf_url == "https://example.org/paper.pdf"
    assert parsed.is_open_access is True
    assert parsed.open_access_status == "GREEN"
    assert parsed.cited_by_count == 42


def test_parse_semantic_scholar_paper_with_missing_optional_fields() -> None:
    parsed = parse_paper(
        {
            "paperId": "s2-minimal",
            "title": None,
            "authors": None,
            "externalIds": None,
            "openAccessPdf": None,
            "publicationTypes": None,
            "citationCount": None,
        }
    )

    assert parsed.title == "Untitled"
    assert parsed.authors == []
    assert parsed.doi is None
    assert parsed.publication_type is None
    assert parsed.pdf_url is None
    assert parsed.is_open_access is False
    assert parsed.open_access_status is None
    assert parsed.cited_by_count == 0


def test_parse_semantic_scholar_paper_requires_source_id() -> None:
    with pytest.raises(KeyError, match="paperId"):
        parse_paper({"title": "Missing source id"})


def test_search_semantic_scholar_builds_request_and_filters_dates() -> None:
    response = MagicMock()
    response.json.return_value = {
        "data": [
            {
                "paperId": "exact-in-range",
                "title": "Exact date in range",
                "publicationDate": "2025-05-01",
            },
            {
                "paperId": "exact-out-of-range",
                "title": "Exact date outside range",
                "publicationDate": "2025-01-01",
            },
            {
                "paperId": "year-in-range",
                "title": "Only publication year",
                "year": 2025,
            },
            {
                "paperId": "unknown-date",
                "title": "No publication date",
            },
        ]
    }
    client = AsyncMock()
    client.get.return_value = response
    request = SearchRequest(
        topic="graph neural networks",
        description="Test Semantic Scholar search",
        start_date=date(2025, 3, 1),
        end_date=date(2025, 6, 30),
        keywords=[],
        max_results=200,
    )

    with (
        patch(
            "module_agent.literature.adapters.sources.semantic_scholar."
            "literature_http_client_manager.get_client",
            return_value=client,
        ) as client_factory,
        patch(
            "module_agent.literature.adapters.sources.semantic_scholar."
            "app_settings.semantic_scholar_api_key",
            "test-api-key",
        ),
        patch(
            "module_agent.literature.adapters.sources.semantic_scholar."
            "semantic_scholar_rate_limiter.wait",
            new_callable=AsyncMock,
        ) as rate_limiter_wait,
    ):
        papers = asyncio.run(search_semantic_scholar(request))

    assert [paper.source_id for paper in papers] == [
        "exact-in-range",
        "year-in-range",
    ]
    rate_limiter_wait.assert_awaited_once_with()
    client_factory.assert_called_once_with()
    client.get.assert_awaited_once_with(
        SEMANTIC_SCHOLAR_URL,
        params={
            "query": "graph neural networks",
            "limit": 100,
            "year": "2025",
            "fields": SEMANTIC_SCHOLAR_FIELDS,
        },
        headers={"x-api-key": "test-api-key"},
    )
    response.raise_for_status.assert_called_once_with()


def test_search_semantic_scholar_retries_temporary_failure() -> None:
    http_request = httpx.Request("GET", SEMANTIC_SCHOLAR_URL)
    first_response = httpx.Response(429, request=http_request)
    successful_response = httpx.Response(
        200,
        json={"data": []},
        request=http_request,
    )
    client = AsyncMock()
    client.get.side_effect = [first_response, successful_response]
    rate_limiter_wait = AsyncMock()
    sleep = AsyncMock()
    request = SearchRequest(
        topic="graph neural networks",
        description="Test retry behavior",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=[],
        max_results=10,
    )

    with (
        patch(
            "module_agent.literature.adapters.sources.semantic_scholar."
            "literature_http_client_manager.get_client",
            return_value=client,
        ),
        patch(
            "module_agent.literature.adapters.sources.semantic_scholar."
            "semantic_scholar_rate_limiter.wait",
            rate_limiter_wait,
        ),
        patch(
            "module_agent.shared.http.retry.asyncio.sleep",
            sleep,
        ),
    ):
        papers = asyncio.run(search_semantic_scholar(request))

    assert papers == []
    assert client.get.await_count == 2
    assert rate_limiter_wait.await_count == 2
    sleep.assert_awaited_once_with(2.0)


def test_search_semantic_scholar_records_exhausted_temporary_failure() -> None:
    http_request = httpx.Request("GET", SEMANTIC_SCHOLAR_URL)
    failed_response = httpx.Response(429, request=http_request)
    client = AsyncMock()
    client.get.return_value = failed_response
    circuit_breaker = MagicMock()
    circuit_breaker.before_call = AsyncMock()
    circuit_breaker.record_failure = AsyncMock()
    circuit_breaker.record_success = AsyncMock()
    request = SearchRequest(
        topic="graph neural networks",
        description="Test exhausted retry behavior",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=[],
        max_results=10,
    )

    with (
        patch(
            "module_agent.literature.adapters.sources.semantic_scholar."
            "literature_http_client_manager.get_client",
            return_value=client,
        ),
        patch(
            "module_agent.literature.adapters.sources.semantic_scholar."
            "semantic_scholar_circuit_breaker",
            circuit_breaker,
        ),
        patch(
            "module_agent.literature.adapters.sources.semantic_scholar."
            "semantic_scholar_rate_limiter.wait",
            new_callable=AsyncMock,
        ),
        patch(
            "module_agent.shared.http.retry.asyncio.sleep",
            new_callable=AsyncMock,
        ),
    ):
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(search_semantic_scholar(request))

    circuit_breaker.before_call.assert_awaited_once_with()
    circuit_breaker.record_failure.assert_awaited_once_with()
    circuit_breaker.record_success.assert_not_awaited()
    assert client.get.await_count == 4


def test_search_semantic_scholar_translates_open_circuit_to_skipped() -> None:
    circuit_breaker = MagicMock()
    circuit_breaker.before_call = AsyncMock(side_effect=CircuitOpenError())
    request = SearchRequest(
        topic="graph neural networks",
        description="Test open circuit behavior",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=[],
        max_results=10,
    )

    with (
        patch(
            "module_agent.literature.adapters.sources.semantic_scholar."
            "semantic_scholar_circuit_breaker",
            circuit_breaker,
        ),
        patch(
            "module_agent.literature.adapters.sources.semantic_scholar."
            "literature_http_client_manager.get_client"
        ) as async_client,
    ):
        with pytest.raises(
            LiteratureSourceSkippedError,
            match="circuit breaker is open",
        ):
            asyncio.run(search_semantic_scholar(request))

    circuit_breaker.before_call.assert_awaited_once_with()
    async_client.assert_not_called()
