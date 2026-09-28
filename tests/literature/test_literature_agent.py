import asyncio
from datetime import date
from unittest.mock import AsyncMock, call

from module_agent.literature.application.agent import LiteratureAgent
from module_agent.literature.domain.search import (
    PaperSearchResult,
    SearchRequest,
    SearchResponse,
    SourceSearchMetric,
    SourceSearchOutcome,
    VenueQualityRequirement,
)
from module_agent.literature.domain.query import (
    LiteratureQueryPlan,
    LiteratureQueryPlanner,
)
from module_agent.literature.domain.ranking import (
    PaperRelevanceAssessment,
    PaperRelevanceResult,
    PaperRelevanceScorer,
)
from module_agent.literature.domain.method import (
    PaperMethodExtractionResult,
    PaperMethodExtractor,
    PaperMethodProfile,
)
from module_agent.literature.domain.llm_metric import (
    LlmCallMetric,
    LlmCallOutcome,
    LlmCallStage,
)
from module_agent.literature.application.search import LiteratureSearchService
from module_agent.literature.application.query_planning import (
    RuleBasedLiteratureQueryPlanner,
)
from module_agent.literature.application.catalog import PaperCatalogService
from module_agent.literature.application.relevance import (
    RuleBasedPaperRelevanceScorer,
)
from module_agent.venue_catalog.application.quality import VenueQualityService
from module_agent.venue_catalog.domain.models import Venue, VenueType


def create_agent(
    search_service: AsyncMock,
    method_extractor: PaperMethodExtractor | None = None,
    query_planner: LiteratureQueryPlanner | None = None,
    relevance_scorer: PaperRelevanceScorer | None = None,
) -> tuple[LiteratureAgent, AsyncMock]:
    venue_quality_service = AsyncMock(spec=VenueQualityService)
    venue_quality_service.matches_requirement.return_value = True
    venue_quality_service.matches_requested_venues.return_value = True
    return (
        LiteratureAgent(
            search_service=search_service,
            venue_quality_service=venue_quality_service,
            query_planner=query_planner or RuleBasedLiteratureQueryPlanner(),
            relevance_scorer=relevance_scorer or RuleBasedPaperRelevanceScorer(),
            method_extractor=method_extractor,
        ),
        venue_quality_service,
    )


def test_literature_agent_propagates_all_llm_call_metrics() -> None:
    request = SearchRequest(
        topic="graph learning",
        description="Find graph learning methods",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=["GNN"],
        max_results=1,
    )
    paper = PaperSearchResult(
        source="openalex", source_id="W1", title="Graph Learning Method"
    )
    stages: tuple[LlmCallStage, ...] = (
        "query_planning",
        "relevance_scoring",
        "method_extraction",
    )
    metrics = [
        LlmCallMetric(
            stage=stage,
            model="test-qwen",
            item_count=1,
            duration_ms=10.0,
            timeout_seconds=180.0,
            outcome=LlmCallOutcome.SUCCESS,
        )
        for stage in stages
    ]
    search_service = AsyncMock(spec=LiteratureSearchService)
    search_service.search.return_value = SearchResponse(results=[paper])
    query_planner = AsyncMock(spec=LiteratureQueryPlanner)
    query_planner.plan.return_value = LiteratureQueryPlan(
        search_queries=["graph learning"], llm_metrics=[metrics[0]]
    )
    relevance_scorer = AsyncMock(spec=PaperRelevanceScorer)
    relevance_scorer.score_many.return_value = PaperRelevanceResult(
        assessments=[
            PaperRelevanceAssessment(
                source=paper.source, source_id=paper.source_id, score=0.9
            )
        ],
        llm_metrics=[metrics[1]],
    )
    method_extractor = AsyncMock(spec=PaperMethodExtractor)
    method_extractor.extract_many.return_value = PaperMethodExtractionResult(
        profiles=[
            PaperMethodProfile(
                source=paper.source, source_id=paper.source_id, confidence=0.8
            )
        ],
        llm_metrics=[metrics[2]],
    )
    agent, _ = create_agent(
        search_service,
        method_extractor,
        query_planner,
        relevance_scorer,
    )

    bundle = asyncio.run(agent.run(request))

    assert bundle.llm_metrics == metrics


def test_literature_agent_returns_method_profiles_and_unique_warnings() -> None:
    request = SearchRequest(
        topic="small object detection",
        description="搜索小目标检测论文",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=["small object detection"],
        max_results=10,
    )
    paper = PaperSearchResult(
        source="openalex",
        source_id="W123",
        title="Small Object Detection Method",
    )
    warning = "method extraction used fallback"
    search_service = AsyncMock(spec=LiteratureSearchService)
    search_service.search.return_value = SearchResponse(
        results=[paper], warnings=[warning]
    )
    profile = PaperMethodProfile(
        source=paper.source,
        source_id=paper.source_id,
        module_type="detector",
        confidence=0.8,
    )
    method_extractor = AsyncMock(spec=PaperMethodExtractor)
    method_extractor.extract_many.return_value = PaperMethodExtractionResult(
        profiles=[profile], warnings=[warning, warning]
    )
    agent, _ = create_agent(search_service, method_extractor)

    bundle = asyncio.run(agent.run(request))

    assert bundle.method_profiles == [profile]
    assert bundle.warnings == [warning]
    method_extractor.extract_many.assert_awaited_once_with(request, [paper])


def test_literature_agent_searches_and_packages_results() -> None:
    # Arrange
    request = SearchRequest(
        topic="small object detection",
        description="搜索小目标检测相关论文",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        venues=["CVPR"],
        keywords=["small object detection"],
        exclusion_keywords=[],
        max_results=10,
    )

    paper = PaperSearchResult(
        source="openalex",
        source_id="W123",
        title="Example Small Object Detection Paper",
        publication_year=2025,
        venue="CVPR",
        doi="10.1000/example",
    )

    search_service = AsyncMock(spec=LiteratureSearchService)
    search_service.search.return_value = SearchResponse(
        results=[paper]
    )

    agent, _ = create_agent(search_service)

    # Act
    bundle = asyncio.run(agent.run(request))

    # Assert
    assert bundle.request == request
    assert bundle.search_queries == ["small object detection"]

    assert len(bundle.candidates) == 1
    assert bundle.candidates[0].source_id == "W123"
    assert bundle.candidates[0].title == "Example Small Object Detection Paper"
    assert bundle.candidates[0].doi == "10.1000/example"

    assert bundle.selected_papers == [paper]
    assert len(bundle.relevance_assessments) == 1
    assert bundle.relevance_assessments[0].source_id == "W123"
    assert bundle.relevance_assessments[0].score == 1.0
    assert bundle.warnings == []

    search_service.search.assert_awaited_once_with(
        request.model_copy(update={"max_results": 50})
    )


def test_literature_agent_deduplicates_multi_query_results() -> None:
    request = SearchRequest(
        topic="small object detection",
        description="搜索遥感小目标检测论文",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        venues=["CVPR"],
        keywords=["remote sensing"],
        exclusion_keywords=[],
        max_results=10,
    )
    duplicated_paper = PaperSearchResult(
        source="openalex",
        source_id="W123",
        title="Example Small Object Detection Paper",
        venue="CVPR",
        doi="10.1000/example",
    )
    search_service = AsyncMock(spec=LiteratureSearchService)
    search_service.search.return_value = SearchResponse(
        results=[duplicated_paper]
    )
    agent, _ = create_agent(search_service)

    bundle = asyncio.run(agent.run(request))

    assert bundle.search_queries == [
        "small object detection",
        "small object detection remote sensing",
    ]
    assert search_service.search.await_count == 2
    assert len(bundle.candidates) == 1
    assert bundle.candidates[0].doi == "10.1000/example"


def test_literature_agent_deduplicates_same_title_with_different_dois() -> None:
    request = SearchRequest(
        topic="lightweight small object detection",
        description="Deduplicate preprint and published versions",
        start_date=date(2024, 1, 1),
        end_date=date(2026, 12, 31),
        keywords=[],
        max_results=10,
    )
    papers = [
        PaperSearchResult(
            source="openalex",
            source_id="published",
            title="SEMA-YOLO: Lightweight Small-Object Detection",
            doi="10.1000/published",
        ),
        PaperSearchResult(
            source="openalex",
            source_id="preprint",
            title="sema yolo lightweight small object detection",
            doi="10.1000/preprint",
        ),
    ]
    search_service = AsyncMock(spec=LiteratureSearchService)
    search_service.search.return_value = SearchResponse(results=papers)
    agent, _ = create_agent(search_service)

    bundle = asyncio.run(agent.run(request))

    assert [paper.source_id for paper in bundle.candidates] == ["published"]
    assert [paper.source_id for paper in bundle.selected_papers] == [
        "published"
    ]


def test_literature_agent_propagates_unique_search_warnings() -> None:
    request = SearchRequest(
        topic="small object detection",
        description="Search multiple query variants",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=["remote sensing"],
        max_results=10,
    )
    warning = "search_secondary failed: TimeoutError: request timed out"
    search_service = AsyncMock(spec=LiteratureSearchService)
    search_service.search.return_value = SearchResponse(
        results=[],
        warnings=[warning],
    )
    agent, _ = create_agent(search_service)

    bundle = asyncio.run(agent.run(request))

    assert search_service.search.await_count == 2
    assert bundle.warnings == [warning]


def test_literature_agent_aggregates_source_metrics_across_queries() -> None:
    request = SearchRequest(
        topic="small object detection",
        description="Collect source metrics for each planned query",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=["remote sensing"],
        max_results=10,
    )
    search_service = AsyncMock(spec=LiteratureSearchService)
    search_service.search.side_effect = [
        SearchResponse(
            source_metrics=[
                SourceSearchMetric(
                    source="search_openalex",
                    query="small object detection",
                    duration_ms=100.0,
                    result_count=2,
                    outcome=SourceSearchOutcome.SUCCESS,
                )
            ]
        ),
        SearchResponse(
            source_metrics=[
                SourceSearchMetric(
                    source="search_semantic_scholar",
                    query="small object detection remote sensing",
                    duration_ms=250.0,
                    result_count=0,
                    outcome=SourceSearchOutcome.FAILED,
                    error_type="HTTPStatusError",
                )
            ]
        ),
    ]
    agent, _ = create_agent(search_service)

    bundle = asyncio.run(agent.run(request))

    assert [metric.source for metric in bundle.source_metrics] == [
        "search_openalex",
        "search_semantic_scholar",
    ]
    assert bundle.source_metrics[1].error_type == "HTTPStatusError"


def test_literature_agent_propagates_unique_query_planning_warnings() -> None:
    request = SearchRequest(
        topic="small object detection",
        description="Use a query planner fallback",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=[],
        max_results=10,
    )
    warning = "LLM query planning failed; rule-based fallback was used"
    query_planner = AsyncMock(spec=LiteratureQueryPlanner)
    query_planner.plan.return_value = LiteratureQueryPlan(
        search_queries=["small object detection"],
        warnings=[warning, warning],
    )
    search_service = AsyncMock(spec=LiteratureSearchService)
    search_service.search.return_value = SearchResponse(results=[])
    venue_quality_service = AsyncMock(spec=VenueQualityService)
    agent = LiteratureAgent(
        search_service=search_service,
        venue_quality_service=venue_quality_service,
        query_planner=query_planner,
        relevance_scorer=RuleBasedPaperRelevanceScorer(),
    )

    bundle = asyncio.run(agent.run(request))

    query_planner.plan.assert_awaited_once_with(request)
    assert bundle.search_queries == ["small object detection"]
    assert bundle.warnings == [warning]


def test_literature_agent_propagates_relevance_warnings() -> None:
    request = SearchRequest(
        topic="graph oversmoothing",
        description="Find methods that address graph oversmoothing",
        start_date=date(2024, 1, 1),
        end_date=date(2026, 12, 31),
        keywords=[],
        max_results=10,
    )
    paper = PaperSearchResult(
        source="openalex",
        source_id="W123",
        title="Addressing Oversmoothing in Graph Neural Networks",
    )
    warning = "Qwen relevance scoring failed; rule-based fallback was used"
    search_service = AsyncMock(spec=LiteratureSearchService)
    search_service.search.return_value = SearchResponse(results=[paper])
    venue_quality_service = AsyncMock(spec=VenueQualityService)
    venue_quality_service.matches_requirement.return_value = True
    relevance_scorer = AsyncMock(spec=PaperRelevanceScorer)
    relevance_scorer.score_many.return_value = PaperRelevanceResult(
        assessments=[
            PaperRelevanceAssessment(
                source=paper.source,
                source_id=paper.source_id,
                score=0.95,
                reason="Directly addresses the requested problem",
            )
        ],
        warnings=[warning, warning],
    )
    agent = LiteratureAgent(
        search_service=search_service,
        venue_quality_service=venue_quality_service,
        query_planner=RuleBasedLiteratureQueryPlanner(),
        relevance_scorer=relevance_scorer,
    )

    bundle = asyncio.run(agent.run(request))

    assert bundle.selected_papers == [paper]
    assert bundle.warnings == [warning]


def test_literature_agent_filters_sorts_and_limits_selected_papers() -> None:
    request = SearchRequest(
        topic="small object detection",
        description="排除综述，并按引用量选择论文",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        venues=["CVPR"],
        keywords=["small object detection"],
        exclusion_keywords=[" Survey "],
        max_results=2,
    )
    papers = [
        PaperSearchResult(
            source="openalex",
            source_id="excluded",
            title="A Survey of Small Object Detection",
            venue="CVPR",
            cited_by_count=100,
        ),
        PaperSearchResult(
            source="openalex",
            source_id="most-cited",
            title="Paper A",
            venue="CVPR",
            cited_by_count=30,
        ),
        PaperSearchResult(
            source="openalex",
            source_id="second-most-cited",
            title="Paper B",
            venue="CVPR",
            cited_by_count=20,
        ),
        PaperSearchResult(
            source="openalex",
            source_id="not-selected",
            title="Paper C",
            venue="CVPR",
            cited_by_count=10,
        ),
    ]
    search_service = AsyncMock(spec=LiteratureSearchService)
    search_service.search.return_value = SearchResponse(results=papers)
    agent, _ = create_agent(search_service)

    bundle = asyncio.run(agent.run(request))

    assert len(bundle.candidates) == 4
    assert [paper.source_id for paper in bundle.selected_papers] == [
        "most-cited",
        "second-most-cited",
    ]
    searched_request = search_service.search.await_args.args[0]
    assert searched_request.max_results == 10
    assert bundle.request.max_results == 2


def test_literature_agent_prioritizes_relevance_over_citations() -> None:
    request = SearchRequest(
        topic="remote sensing small object detection",
        description="Prefer papers that directly address the requested topic",
        start_date=date(2024, 1, 1),
        end_date=date(2026, 12, 31),
        keywords=[],
        max_results=2,
    )
    broad_highly_cited_paper = PaperSearchResult(
        source="openalex",
        source_id="broad-review",
        title="A Highly Cited Computer Vision Survey",
        abstract="This survey briefly discusses object detection.",
        cited_by_count=1000,
    )
    relevant_low_cited_paper = PaperSearchResult(
        source="semantic_scholar",
        source_id="direct-match",
        title="Remote Sensing Small Object Detection",
        cited_by_count=1,
    )
    search_service = AsyncMock(spec=LiteratureSearchService)
    search_service.search.return_value = SearchResponse(
        results=[broad_highly_cited_paper, relevant_low_cited_paper]
    )
    agent, _ = create_agent(search_service)

    bundle = asyncio.run(agent.run(request))

    assert [paper.source_id for paper in bundle.selected_papers] == [
        "direct-match",
        "broad-review",
    ]


def test_literature_agent_filters_and_normalizes_requested_venues() -> None:
    request = SearchRequest(
        topic="machine learning",
        description="只搜索指定期刊",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        venues=[" IEEE   Access "],
        keywords=[],
        exclusion_keywords=[],
        max_results=10,
    )
    papers = [
        PaperSearchResult(
            source="openalex",
            source_id="matching",
            title="Matching Paper",
            venue="ieee access",
        ),
        PaperSearchResult(
            source="openalex",
            source_id="different",
            title="Different Venue",
            venue="NeurIPS",
        ),
        PaperSearchResult(
            source="openalex",
            source_id="missing",
            title="Missing Venue",
            venue=None,
        ),
    ]
    search_service = AsyncMock(spec=LiteratureSearchService)
    search_service.search.return_value = SearchResponse(results=papers)
    agent, venue_quality_service = create_agent(search_service)
    venue_quality_service.matches_requested_venues.side_effect = [True, False]

    bundle = asyncio.run(agent.run(request))

    assert len(bundle.candidates) == 3
    assert [paper.source_id for paper in bundle.selected_papers] == ["matching"]
    assert venue_quality_service.matches_requested_venues.await_args_list == [
        call("ieee access", request.venues),
        call("NeurIPS", request.venues),
    ]


def test_literature_agent_filters_by_quality_without_specific_venues() -> None:
    requirement = VenueQualityRequirement(
        ranking_system="ccf",
        allowed_levels=["A"],
    )
    request = SearchRequest(
        topic="computer vision",
        description="搜索 CCF-A 论文",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        venues=[],
        venue_quality=requirement,
        keywords=[],
        exclusion_keywords=[],
        max_results=10,
    )
    papers = [
        PaperSearchResult(
            source="openalex",
            source_id="accepted",
            title="Accepted Paper",
            venue="CVPR",
        ),
        PaperSearchResult(
            source="openalex",
            source_id="rejected",
            title="Rejected Paper",
            venue="Other Conference",
        ),
    ]
    search_service = AsyncMock(spec=LiteratureSearchService)
    search_service.search.return_value = SearchResponse(results=papers)
    agent, venue_quality_service = create_agent(search_service)
    venue_quality_service.matches_requirement.side_effect = [True, False]

    bundle = asyncio.run(agent.run(request))

    assert len(bundle.candidates) == 2
    assert [paper.source_id for paper in bundle.selected_papers] == ["accepted"]
    assert venue_quality_service.matches_requirement.await_args_list == [
        call("CVPR", requirement),
        call("Other Conference", requirement),
    ]


def test_literature_agent_persists_only_selected_papers() -> None:
    request = SearchRequest(
        topic="computer vision",
        description="保存最终选中的论文",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        keywords=[],
        max_results=1,
    )
    papers = [
        PaperSearchResult(
            source="openalex",
            source_id="selected",
            title="Selected Paper",
            authors=["Author One"],
            venue="CVPR",
            doi="10.1000/selected",
            cited_by_count=20,
        ),
        PaperSearchResult(
            source="openalex",
            source_id="not-selected",
            title="Other Paper",
            venue="Other Conference",
            cited_by_count=10,
        ),
    ]
    search_service = AsyncMock(spec=LiteratureSearchService)
    search_service.search.return_value = SearchResponse(results=papers)
    venue_quality_service = AsyncMock(spec=VenueQualityService)
    venue_quality_service.matches_requirement.return_value = True
    venue_quality_service.resolve_venue.return_value = Venue(
        id=42,
        canonical_name="CVPR",
        venue_type=VenueType.CONFERENCE,
    )
    paper_catalog_service = AsyncMock(spec=PaperCatalogService)
    paper_catalog_service.upsert.side_effect = lambda paper: paper.model_copy(
        update={"id": 99}
    )
    agent = LiteratureAgent(
        search_service=search_service,
        venue_quality_service=venue_quality_service,
        query_planner=RuleBasedLiteratureQueryPlanner(),
        relevance_scorer=RuleBasedPaperRelevanceScorer(),
        paper_catalog_service=paper_catalog_service,
    )

    bundle = asyncio.run(agent.run(request))

    assert [paper.source_id for paper in bundle.selected_papers] == ["selected"]
    assert len(bundle.persisted_papers) == 1
    assert bundle.persisted_papers[0].id == 99
    persisted = paper_catalog_service.upsert.await_args.args[0]
    assert persisted.source_id == "selected"
    assert persisted.venue_id == 42
    assert persisted.venue_name == "CVPR"
