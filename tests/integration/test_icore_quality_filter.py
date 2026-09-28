import asyncio
import os
from datetime import date
from unittest.mock import AsyncMock

import pytest

from module_agent.literature.application.agent import LiteratureAgent
from module_agent.literature.domain.search import (
    PaperSearchResult,
    SearchRequest,
    SearchResponse,
    VenueQualityRequirement,
)
from module_agent.shared.database import (
    async_session_factory,
    database_engine,
)
from module_agent.venue_catalog.adapters.database.repository import (
    SqlAlchemyVenueRepository,
)
from module_agent.literature.application.search import LiteratureSearchService
from module_agent.literature.application.query_planning import (
    RuleBasedLiteratureQueryPlanner,
)
from module_agent.literature.application.relevance import (
    RuleBasedPaperRelevanceScorer,
)
from module_agent.venue_catalog.application.quality import VenueQualityService


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="set RUN_DATABASE_INTEGRATION_TESTS=1 to test the imported catalog",
)


def _request(level: str) -> SearchRequest:
    return SearchRequest(
        topic="computer vision",
        description="验证 ICORE 会议等级筛选",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        keywords=[],
        max_results=10,
        venue_quality=VenueQualityRequirement(
            ranking_system="core",
            allowed_levels=[level],
        ),
    )


async def _run_agent(level: str) -> list[PaperSearchResult]:
    async with async_session_factory() as session:
        search_service = AsyncMock(spec=LiteratureSearchService)
        paper = PaperSearchResult(
            source="test",
            source_id="cvpr-paper",
            title="Example CVPR Paper",
            venue="CVPR",
        )
        search_service.search.return_value = SearchResponse(results=[paper])

        quality_service = VenueQualityService(
            SqlAlchemyVenueRepository(session)
        )
        agent = LiteratureAgent(
            search_service=search_service,
            venue_quality_service=quality_service,
            query_planner=RuleBasedLiteratureQueryPlanner(),
            relevance_scorer=RuleBasedPaperRelevanceScorer(),
        )
        bundle = await agent.run(_request(level))
        return bundle.selected_papers


def test_literature_agent_uses_imported_icore_ranking() -> None:
    async def verify() -> None:
        try:
            assert await _run_agent("A*") != []
            assert await _run_agent("A") == []
        finally:
            await database_engine.dispose()

    asyncio.run(verify())
