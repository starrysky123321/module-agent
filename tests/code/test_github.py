import asyncio

import httpx
import pytest

import module_agent.code.adapters.pdf_repository as pdf_repository
from module_agent.code.adapters.github import GitHubRepositorySearcher
from module_agent.code.application.scoring import RepositoryScoringService
from module_agent.code.domain.repository import (
    RepositoryEvidenceType,
    RepositoryOrigin,
)
from module_agent.code.domain.request import CodePaperInput


def make_paper() -> CodePaperInput:
    return CodePaperInput(
        paper_id=1,
        source="openalex",
        source_id="W1",
        title="Reliable Graph Learning",
        authors=["Alice Zhang"],
        doi="10.1000/graph.1",
    )


def test_github_searcher_loads_repository_metadata_and_readme() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/search/repositories":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "full_name": "alice/graph-learning",
                            "html_url": "https://github.com/alice/graph-learning",
                            "owner": {"login": "alice"},
                            "description": "Official implementation",
                            "topics": ["graph-neural-networks"],
                            "default_branch": "main",
                            "archived": False,
                            "license": {"spdx_id": "MIT"},
                        }
                    ]
                },
            )
        if request.url.path == "/repos/alice/graph-learning/readme":
            return httpx.Response(200, text="# Reliable Graph Learning")
        raise AssertionError(f"Unexpected request: {request.url}")

    async def run_search() -> list:
        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            searcher = GitHubRepositorySearcher(
                client,
                token="test-token",
            )
            return await searcher.search(make_paper(), limit=5)

    candidates = asyncio.run(run_search())

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.full_name == "alice/graph-learning"
    assert candidate.readme_text == "# Reliable Graph Learning"
    assert candidate.default_branch == "main"
    assert candidate.license_spdx == "MIT"
    assert requests[0].url.params["per_page"] == "5"
    assert requests[0].url.params["q"] == (
        '"Reliable Graph Learning" in:name,description,readme'
    )
    assert requests[0].headers["authorization"] == "Bearer test-token"
    assert requests[1].headers["accept"] == (
        "application/vnd.github.raw+json"
    )


def test_github_searcher_tolerates_missing_readme_and_skips_bad_items() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/repositories":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"full_name": "missing-fields"},
                        {
                            "full_name": "alice/no-readme",
                            "html_url": "https://github.com/alice/no-readme",
                            "owner": {"login": "alice"},
                            "license": {"spdx_id": "NOASSERTION"},
                        },
                    ]
                },
            )
        return httpx.Response(404)

    async def run_search() -> list:
        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            return await GitHubRepositorySearcher(client).search(make_paper())

    candidates = asyncio.run(run_search())

    assert len(candidates) == 1
    assert candidates[0].readme_text is None
    assert candidates[0].license_spdx is None


def test_github_searcher_returns_empty_without_readme_requests() -> None:
    request_count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json={"items": []})

    async def run_search() -> list:
        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            return await GitHubRepositorySearcher(client).search(make_paper())

    assert asyncio.run(run_search()) == []
    assert request_count == 1


def test_github_searcher_includes_repository_found_in_pdf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_download(url: str, **_: object) -> bytes:
        assert url == "https://papers.test/paper.pdf"
        return b"%PDF-fake"

    def fake_extract(pdf_bytes: bytes) -> list[str]:
        assert pdf_bytes == b"%PDF-fake"
        return ["https://github.com/alice/pdf-code"]

    monkeypatch.setattr(pdf_repository, "download", fake_download)
    monkeypatch.setattr(pdf_repository, "extract", fake_extract)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/repositories":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "full_name": "alice/pdf-code",
                            "html_url": "https://github.com/alice/pdf-code",
                            "owner": {"login": "alice"},
                            "description": "Code linked by the paper PDF",
                            "topics": [],
                            "default_branch": "main",
                            "archived": False,
                            "license": {"spdx_id": "MIT"},
                        }
                    ]
                },
            )
        if request.url.path == "/repos/alice/pdf-code":
            return httpx.Response(
                200,
                json={
                    "full_name": "alice/pdf-code",
                    "html_url": "https://github.com/alice/pdf-code",
                    "owner": {"login": "alice"},
                    "description": "Code linked by the paper PDF",
                    "topics": [],
                    "default_branch": "main",
                    "archived": False,
                    "license": {"spdx_id": "MIT"},
                },
            )
        if request.url.path == "/repos/alice/pdf-code/readme":
            return httpx.Response(200, text="# PDF Code")
        raise AssertionError(f"Unexpected request: {request.url}")

    async def run_search() -> list:
        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            searcher = GitHubRepositorySearcher(
                client,
                token="test-token",
            )
            paper = make_paper().model_copy(
                update={"pdf_url": "https://papers.test/paper.pdf"}
            )
            return await searcher.search(paper, limit=5)

    candidates = asyncio.run(run_search())

    assert len(candidates) == 1
    assert candidates[0].full_name == "alice/pdf-code"
    assert candidates[0].readme_text == "# PDF Code"
    assert candidates[0].evidence[0].evidence_type is (
        RepositoryEvidenceType.PAPER_URL
    )
    assert candidates[0].evidence[0].weight == 0.95

    scored = RepositoryScoringService().score(
        make_paper().model_copy(
            update={"pdf_url": "https://papers.test/paper.pdf"}
        ),
        candidates[0],
    )
    assert scored.origin is RepositoryOrigin.OFFICIAL
    assert scored.confidence >= 0.7


def test_github_searcher_keeps_title_results_when_pdf_download_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_download(_: str, **__: object) -> bytes:
        request = httpx.Request("GET", "https://papers.test/missing.pdf")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError(
            "PDF not found",
            request=request,
            response=response,
        )

    monkeypatch.setattr(pdf_repository, "download", failing_download)

    candidates = asyncio.run(
        _search_with_title_result_and_pdf(
            "https://papers.test/missing.pdf"
        )
    )

    assert [candidate.full_name for candidate in candidates] == [
        "alice/title-result"
    ]


def test_github_searcher_keeps_title_results_when_pdf_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def download_invalid_pdf(_: str, **__: object) -> bytes:
        return b"this is not a PDF"

    monkeypatch.setattr(pdf_repository, "download", download_invalid_pdf)

    candidates = asyncio.run(
        _search_with_title_result_and_pdf(
            "https://papers.test/invalid.pdf"
        )
    )

    assert [candidate.full_name for candidate in candidates] == [
        "alice/title-result"
    ]


async def _search_with_title_result_and_pdf(
    pdf_url: str,
) -> list:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/repositories":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "full_name": "alice/title-result",
                            "html_url": "https://github.com/alice/title-result",
                            "owner": {"login": "alice"},
                            "description": "Found by title search",
                            "topics": [],
                            "default_branch": "main",
                            "archived": False,
                            "license": {"spdx_id": "MIT"},
                        }
                    ]
                },
            )
        if request.url.path == "/repos/alice/title-result/readme":
            return httpx.Response(200, text="# Title Result")
        raise AssertionError(f"Unexpected request: {request.url}")

    async with httpx.AsyncClient(
        base_url="https://api.github.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        paper = make_paper().model_copy(update={"pdf_url": pdf_url})
        return await GitHubRepositorySearcher(client).search(paper)


def test_github_searcher_propagates_rate_limit_response() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "rate limit exceeded"})

    async def run_search() -> None:
        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            await GitHubRepositorySearcher(client).search(make_paper())

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(run_search())


@pytest.mark.parametrize("limit", [0, 101])
def test_github_searcher_rejects_invalid_limit(limit: int) -> None:
    async def run_search() -> None:
        async with httpx.AsyncClient(
            base_url="https://api.github.test",
        ) as client:
            await GitHubRepositorySearcher(client).search(
                make_paper(),
                limit=limit,
            )

    with pytest.raises(ValueError, match="between 1 and 100"):
        asyncio.run(run_search())
