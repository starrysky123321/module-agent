import asyncio

import httpx
import pytest

import module_agent.code.adapters.paper_links as paper_links
from module_agent.code.adapters.paper_links import PaperLinkRepositorySearcher
from module_agent.code.domain.request import CodePaperInput


def test_paper_link_searcher_reads_landing_and_direct_supplementary_links(
    monkeypatch,
) -> None:
    async def fake_download_text(url: str, **_: object) -> str:
        assert url == "https://papers.test/project"
        return '<a href="https://github.com/alice/official?tab=readme">code</a>'

    monkeypatch.setattr(paper_links, "download_text", fake_download_text)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/alice/official":
            return httpx.Response(200, json={"full_name": "alice/official"})
        if request.url.path == "/repos/bob/supplement":
            return httpx.Response(200, json={"full_name": "bob/supplement"})
        raise AssertionError(f"Unexpected request: {request.url}")

    async def run() -> list:
        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            return await PaperLinkRepositorySearcher(client).search_github_links(
                CodePaperInput(
                    paper_id=1,
                    source="openalex",
                    source_id="W1",
                    title="Example",
                    landing_page_url="https://papers.test/project",
                    supplementary_urls=[
                        "https://github.com/bob/supplement.git"
                    ],
                )
            )

    result = asyncio.run(run())

    assert [item[0]["full_name"] for item in result] == [
        "alice/official",
        "bob/supplement",
    ]
    assert result[0][1] == "https://papers.test/project"


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_paper_link_searcher_rejects_invalid_limit(limit: int) -> None:
    async def run() -> None:
        paper = CodePaperInput(
            paper_id=1,
            source="openalex",
            source_id="W1",
            title="Example paper",
        )

        async with httpx.AsyncClient() as client:
            searcher = PaperLinkRepositorySearcher(client)

            with pytest.raises(ValueError, match="between 1 and 100"):
                await searcher.search_github_links(
                    paper,
                    limit=limit,
                )

    asyncio.run(run())
