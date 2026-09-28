import asyncio

import httpx
import pytest

from module_agent.code.adapters.pdf_repository import (
    PdfRepositorySearcher,
    download,
    extract_github_links,
    parse_github_repo_url,
)
from module_agent.code.domain.errors import (
    InvalidPdfContentError,
    PdfTooLargeError,
    UnsafePdfUrlError,
)
from module_agent.code.domain.request import CodePaperInput


PUBLIC_PDF_URL = "https://93.184.216.34/paper.pdf"


def _run_download(
    handler: httpx.MockTransport,
    *,
    url: str = PUBLIC_PDF_URL,
    max_bytes: int = 1024,
) -> bytes:
    async def run() -> bytes:
        async with httpx.AsyncClient(transport=handler) as client:
            return await download(
                url,
                max_bytes=max_bytes,
                client=client,
            )

    return asyncio.run(run())


def test_download_accepts_pdf_within_limit() -> None:
    content = b"%PDF-1.7\nvalid test content"
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            content=content,
            headers={"Content-Type": "application/pdf"},
        )
    )

    assert _run_download(transport) == content


def test_download_accepts_pdf_header_with_generic_content_type() -> None:
    content = b"%PDF-1.7\nvalid test content"
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            content=content,
            headers={"Content-Type": "application/octet-stream"},
        )
    )

    assert _run_download(transport) == content


def test_download_rejects_non_pdf_content() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            content=b"<html>not a PDF</html>",
            headers={"Content-Type": "text/html"},
        )
    )

    with pytest.raises(InvalidPdfContentError):
        _run_download(transport)


def test_download_rejects_declared_oversized_pdf() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            content=b"%PDF-1.7",
            headers={"Content-Length": "2048"},
        )
    )

    with pytest.raises(PdfTooLargeError, match="declares 2048 bytes"):
        _run_download(transport, max_bytes=1024)


def test_download_rejects_streamed_oversized_pdf() -> None:
    content = b"%PDF-1.7\n" + b"x" * 1024
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            content=content,
            headers={"Content-Length": "unknown"},
        )
    )

    with pytest.raises(PdfTooLargeError, match="exceeds"):
        _run_download(transport, max_bytes=100)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/paper.pdf",
        "http://127.0.0.1/paper.pdf",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/paper.pdf",
        "https://user:password@example.com/paper.pdf",
    ],
)
def test_download_rejects_unsafe_url(url: str) -> None:
    transport = httpx.MockTransport(
        lambda _: pytest.fail("unsafe URL must not be requested")
    )

    with pytest.raises(UnsafePdfUrlError):
        _run_download(transport, url=url)


def test_download_rechecks_redirect_target() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"Location": "http://127.0.0.1/private.pdf"},
        )

    with pytest.raises(UnsafePdfUrlError):
        _run_download(httpx.MockTransport(handler))


def test_extract_github_links_normalizes_wrapped_and_git_urls() -> None:
    text = (
        "Code: https://github . com / alice / segment-\n"
        "anything.git and https://github.com/bob/repo?tab=readme"
    )

    assert extract_github_links(text) == [
        "https://github.com/alice/segment-anything",
        "https://github.com/bob/repo",
    ]
    assert parse_github_repo_url(
        "https://github.com/alice/segment-anything.git?download=1"
    ) == ("alice", "segment-anything")


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_pdf_repository_search_rejects_invalid_limit(limit: int) -> None:
    async def run() -> None:
        paper = CodePaperInput(
            paper_id=1,
            source="openalex",
            source_id="W1",
            title="Example paper",
        )

        async with httpx.AsyncClient() as client:
            searcher = PdfRepositorySearcher(client)

            with pytest.raises(ValueError, match="between 1 and 100"):
                await searcher.search_github_links(
                    paper,
                    limit=limit,
                )

    asyncio.run(run())
