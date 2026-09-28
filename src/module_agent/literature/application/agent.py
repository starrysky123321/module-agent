from module_agent.literature.application.search import LiteratureSearchService
from module_agent.literature.application.catalog import PaperCatalogService
from module_agent.venue_catalog.application.quality import VenueQualityService

from typing import Any

from langgraph.graph import END, START, StateGraph

from module_agent.literature.domain.search import (
    LiteratureAgentState,
    LiteratureBundle,
    PaperSearchResult,
    SearchRequest,
)
from module_agent.literature.domain.paper import Paper
from module_agent.literature.domain.method import (
    PaperMethodExtractor,
    PaperMethodProfile,
)
from module_agent.literature.domain.llm_metric import LlmCallMetric
from module_agent.literature.domain.query import LiteratureQueryPlanner
from module_agent.literature.domain.ranking import (
    PaperRelevanceAssessment,
    PaperRelevanceScorer,
)
from module_agent.literature.application.deduplication import deduplicate_papers
class LiteratureAgent:
    """协调该 Agent 的业务流程。"""
    def __init__(
        self,
        search_service: LiteratureSearchService,
        venue_quality_service: VenueQualityService,
        query_planner: LiteratureQueryPlanner,
        relevance_scorer: PaperRelevanceScorer,
        paper_catalog_service: PaperCatalogService | None = None,
        method_extractor: PaperMethodExtractor | None = None,
    ) -> None:
        """初始化当前对象。"""
        self.search_service = search_service
        self.venue_quality_service = venue_quality_service
        self.query_planner = query_planner
        self.relevance_scorer = relevance_scorer
        self.paper_catalog_service = paper_catalog_service
        self.method_extractor = method_extractor
        self.graph = self._build_graph()
        
    def _build_graph(self):
        builder = StateGraph(LiteratureAgentState)

        builder.add_node("plan_queries", self._plan_queries_node)
        builder.add_node("search", self._search_node)
        builder.add_node("deduplicate", self._deduplicate_node)
        builder.add_node("select_papers", self._select_papers_node)
        builder.add_node("persist_papers", self._persist_papers_node)
        builder.add_node("extract_method", self._extract_method)
        
        builder.add_edge(START, "plan_queries")
        builder.add_edge("plan_queries", "search")
        builder.add_edge("search", "deduplicate")
        builder.add_edge("deduplicate", "select_papers")
        builder.add_edge("select_papers", "extract_method")
        builder.add_edge("extract_method", "persist_papers")
        builder.add_edge("persist_papers", END)

        return builder.compile()
    
    
    async def _extract_method(self, state: LiteratureAgentState) -> dict[str, Any]:
        if not self.method_extractor:
            return {"method_profiles": []}
        
        papers = [PaperSearchResult.model_validate(paper) for paper in state.get("selected_papers", [])]
        warnings = list(state.get("warnings", []))
        request = SearchRequest.model_validate(state["request"])
        result = await self.method_extractor.extract_many(request, papers)
        
        
        warnings.extend(result.warnings)

        return {
            "method_profiles": [
                profile.model_dump(mode="json") for profile in result.profiles
            ],
            "warnings": list(dict.fromkeys(warnings)),
            "llm_metrics": [
                *state.get("llm_metrics", []),
                *(metric.model_dump(mode="json") for metric in result.llm_metrics),
            ],
        }
    
    async def _select_papers_node(self, state: LiteratureAgentState,) -> dict[str, Any]:
        request = SearchRequest.model_validate(state["request"])
        papers = [PaperSearchResult.model_validate(paper) for paper in state.get("candidates", [])]
        venues = request.venues or []
        
        normalized_venues = {
            " ".join(venue.casefold().split())
            for venue in venues
            if venue.strip()
        }
        
        exclusion_keywords = [keyword.strip().casefold() 
                              for keyword in request.exclusion_keywords or []
                              if keyword and keyword.strip()]
        
        
        eligible_papers: list[PaperSearchResult] = []
        
        for paper in papers:
            if normalized_venues:
                if paper.venue is None:
                    continue

                matches_venue = await self.venue_quality_service.matches_requested_venues(
                    paper.venue,
                    request.venues,
                )
                if not matches_venue:
                    continue
            
            paper_text = " ".join(
                text for text in [paper.title, paper.abstract] if text
            ).casefold()
            
            if any(keyword in paper_text for keyword in exclusion_keywords):
                continue
            
            matches_quality = await self.venue_quality_service.matches_requirement(
                paper.venue,
                request.venue_quality,
            )
            if not matches_quality:
                continue
            
            eligible_papers.append(paper)
        
        if not eligible_papers:
            return {"selected_papers": []}
        
        relevance_result = await self.relevance_scorer.score_many(
            request=request,
            search_queries=state.get("search_queries", []),
            papers=eligible_papers,
        )

        assessments = relevance_result.assessments
        
        relevance_scores = {
            (assessment.source, assessment.source_id): assessment.score
            for assessment in assessments
        }

        
        selected_papers = sorted(
            eligible_papers,
            key=lambda paper: (
                relevance_scores.get(
                    (paper.source, paper.source_id),
                    0.0,
                ),
                paper.cited_by_count,
            ),
            reverse=True,
        )
        
        selected_papers = selected_papers[:request.max_results]
        
        warnings = list(state.get("warnings", []))
        warnings.extend(relevance_result.warnings)

        return {
            "selected_papers": [
                paper.model_dump(mode="json")
                for paper in selected_papers
            ],
            "relevance_assessments": [
                assessment.model_dump(mode="json")
                for assessment in assessments
            ],
            "warnings": list(dict.fromkeys(warnings)),
            "llm_metrics": [
                *state.get("llm_metrics", []),
                *(metric.model_dump(mode="json") for metric in relevance_result.llm_metrics),
            ],
        }

    async def _persist_papers_node(
        self,
        state: LiteratureAgentState,
    ) -> dict[str, Any]:
        if self.paper_catalog_service is None:
            return {"persisted_papers": []}

        persisted_papers: list[Paper] = []
        for raw_paper in state.get("selected_papers", []):
            result = PaperSearchResult.model_validate(raw_paper)
            venue = await self.venue_quality_service.resolve_venue(result.venue)
            paper = Paper(
                source=result.source,
                source_id=result.source_id,
                title=result.title,
                authors=result.authors,
                publication_year=result.publication_year,
                publication_date=result.publication_date,
                publication_type=result.publication_type,
                venue_id=venue.id if venue is not None else None,
                venue_name=result.venue,
                doi=result.doi,
                abstract=result.abstract,
                landing_page_url=result.landing_page_url,
                pdf_url=result.pdf_url,
                is_open_access=result.is_open_access,
                open_access_status=result.open_access_status,
                cited_by_count=result.cited_by_count,
            )
            persisted_papers.append(
                await self.paper_catalog_service.upsert(paper)
            )

        return {
            "persisted_papers": [
                paper.model_dump(mode="json") for paper in persisted_papers
            ]
        }
    
    
    async def _deduplicate_node(self, state: LiteratureAgentState,) -> dict[str, Any]:
        raw_papers = state.get("candidates", [])
        papers = [PaperSearchResult.model_validate(raw_paper) for raw_paper in raw_papers]
        unique_papers = deduplicate_papers(papers)
        
        return {"candidates": [paper.model_dump(mode="json") for paper in unique_papers]}


    async def _plan_queries_node(self, state: LiteratureAgentState,) -> dict[str, Any]:
        request = SearchRequest.model_validate(state["request"])
        
        plan = await self.query_planner.plan(request)
        
        warnings = list(state.get("warnings", []))
        warnings.extend(plan.warnings)
        warnings = list(dict.fromkeys(warnings))
        
        return {
            "search_queries": plan.search_queries,
            "warnings": warnings,
            "llm_metrics": [
                *state.get("llm_metrics", []),
                *(metric.model_dump(mode="json") for metric in plan.llm_metrics),
            ],
        }
    
    async def _search_node(self, state: LiteratureAgentState,) -> dict[str, Any]:
        request = SearchRequest.model_validate(state["request"])
        responses = []
        
        warnings = list(state.get("warnings", []))
        source_metrics = list(state.get("source_metrics", []))

        for query in state.get("search_queries", []):
            new_request = request.model_copy(update={"topic": query, "max_results": min(request.max_results * 5, 200)})
            response = await self.search_service.search(new_request)
            responses.append(response)
            warnings.extend(response.warnings)
            source_metrics.extend(
                metric.model_dump(mode="json")
                for metric in response.source_metrics
            )

        warnings = list(dict.fromkeys(warnings))

        candidates = [paper.model_dump(mode="json") for response in responses for paper in response.results]
        
        
        return {
            "candidates": candidates,
            "warnings": warnings,
            "source_metrics": source_metrics,
        }
        

    async def run(self, request: SearchRequest) -> LiteratureBundle:
        
        """执行当前任务。"""
        init_state: LiteratureAgentState = {
            "request": request.model_dump(mode="json"),
            "search_queries": [],
            "candidates": [],
            "selected_papers": [],
            "relevance_assessments": [],
            "persisted_papers": [],
            "warnings": [],
            "source_metrics": [],
            "method_profiles": [],
            "llm_metrics": [],
       }
        
        result = await self.graph.ainvoke(init_state)
        
        candidates = [PaperSearchResult.model_validate(paper) for paper in result["candidates"]]
        
        return LiteratureBundle(
            request=request,
            search_queries=result.get("search_queries", []),
            candidates=candidates,
            selected_papers=[PaperSearchResult.model_validate(paper) 
                             for paper in result.get("selected_papers", [])],
            relevance_assessments=[
                PaperRelevanceAssessment.model_validate(assessment)
                for assessment in result.get("relevance_assessments", [])
            ],
            persisted_papers=[
                Paper.model_validate(paper)
                for paper in result.get("persisted_papers", [])
            ],
            warnings=result.get("warnings", []),
            source_metrics=result.get("source_metrics", []),
            method_profiles=[
                PaperMethodProfile.model_validate(profile)
                for profile in result.get("method_profiles", [])
            ],
            llm_metrics=[
                LlmCallMetric.model_validate(metric)
                for metric in result.get("llm_metrics", [])
            ],
        )
        
