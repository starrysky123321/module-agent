import asyncio
import re
import time
from collections.abc import Sequence

from module_agent.shared.logging import logger
from module_agent.literature.domain.search import PaperSearchResult, SearchRequest
from module_agent.literature.domain.ranking import (
    PaperRelevanceAssessment,
    PaperRelevanceResult,
    PaperRelevanceScorer,
)
from module_agent.literature.domain.llm_metric import LlmCallOutcome
from module_agent.literature.application.llm_observability import (
    record_llm_call,
    validate_timeout_seconds,
)

STOP_WORDS = frozenset({
    "a", "an", "the", "of", "in", "on",
    "for", "and", "or", "to", "with",
    "using", "based",
})

MAX_SEMANTIC_SHORTLIST_SIZE = 20
METHOD_REQUEST_TERMS = (
    "algorithm",
    "method",
    "module",
    "算法",
    "方法",
    "模块",
)
REVIEW_TERMS = ("survey", "review", "综述")


def _tokenize(text: str) -> set[str]:
    normalized_text = text.casefold()
    normalized_text = re.sub(
        r"\bover[\s_-]+smoothing\b",
        "oversmoothing",
        normalized_text,
    )
    normalized_text = re.sub(
        r"\bover[\s_-]+squashing\b",
        "oversquashing",
        normalized_text,
    )

    tokens = set(re.findall(r"[a-z0-9]+", normalized_text))

    return tokens - STOP_WORDS


def _score_query(
    query_terms: set[str],
    title_terms: set[str],
    abstract_terms: set[str],
) -> tuple[float, set[str]]:
    if not query_terms:
        return 0.0, set()

    score = 0.0
    matched_terms = set()
    
    for term in query_terms:
        if term in title_terms:
            matched_terms.add(term)
            score += 1.0
        elif term in abstract_terms:
            score += 0.5
            matched_terms.add(term)

    score /= len(query_terms)
    return score, matched_terms


class RuleBasedPaperRelevanceScorer:
    """封装 RuleBasedPaperRelevanceScorer 相关的数据和行为。"""
    async def score_many(
        self,
        request: SearchRequest,
        search_queries: Sequence[str],
        papers: Sequence[PaperSearchResult],
    ) -> PaperRelevanceResult:
        """评分全部输入并按可信度排序。"""
        if not papers:
            return PaperRelevanceResult()

        # 没有规划查询时，退回topic和keywords
        effective_queries = search_queries or [
            request.topic,
            *request.keywords,
        ]

        # 查询只需要分词一次，不必对每篇论文重复分词
        query_term_sets = [
            _tokenize(query)
            for query in effective_queries
        ]

        assessments: list[PaperRelevanceAssessment] = []
        request_text = " ".join(
            [request.topic, request.description, *request.keywords]
        ).casefold()
        requires_method = any(
            term in request_text
            for term in METHOD_REQUEST_TERMS
        )

        for paper in papers:
            title_terms = _tokenize(paper.title)
            abstract_terms = _tokenize(paper.abstract or "")

            best_score = 0.0
            best_matched_terms: set[str] = set()

            for query_terms in query_term_sets:
                score, matched_terms = _score_query(
                    query_terms=query_terms,
                    title_terms=title_terms,
                    abstract_terms=abstract_terms,
                )

                if score > best_score:
                    best_score = score
                    best_matched_terms = matched_terms

            sorted_matched_terms = sorted(best_matched_terms)
            paper_type_text = " ".join(
                [paper.title, paper.publication_type or ""]
            ).casefold()
            is_review = any(
                term in paper_type_text
                for term in REVIEW_TERMS
            )
            review_was_capped = requires_method and is_review
            if review_was_capped:
                best_score = min(best_score, 0.5)

            if sorted_matched_terms:
                reason = (
                    f"Matched {len(sorted_matched_terms)} "
                    "search terms"
                )
            else:
                reason = "No lexical overlap with search queries"

            if review_was_capped:
                reason += "; review capped for a method-focused request"

            assessments.append(
                PaperRelevanceAssessment(
                    source=paper.source,
                    source_id=paper.source_id,
                    score=best_score,
                    matched_terms=sorted_matched_terms,
                    reason=reason,
                )
            )

        return PaperRelevanceResult(assessments=assessments)


class FallbackPaperRelevanceScorer:
    """封装 FallbackPaperRelevanceScorer 相关的数据和行为。"""
    def __init__(
        self,
        primary: PaperRelevanceScorer,
        fallback: PaperRelevanceScorer,
        *,
        timeout_seconds: float | None = None,
        model: str = "unknown",
    ) -> None:
        """初始化当前对象。"""
        validate_timeout_seconds(timeout_seconds)
        self.primary = primary
        self.fallback = fallback
        self.timeout_seconds = timeout_seconds
        self.model = model

    async def score_many(
        self,
        request: SearchRequest,
        search_queries: Sequence[str],
        papers: Sequence[PaperSearchResult],
    ) -> PaperRelevanceResult:
        """评分全部输入并按可信度排序。"""
        started_at = time.perf_counter()
        try:
            if self.timeout_seconds is None or not papers:
                return await self.primary.score_many(
                    request, search_queries, papers
                )
            async with asyncio.timeout(self.timeout_seconds):
                primary_result = await self.primary.score_many(
                    request, search_queries, papers
                )
            metric = record_llm_call(
                stage="relevance_scoring",
                model=self.model,
                item_count=len(papers),
                started_at=started_at,
                timeout_seconds=self.timeout_seconds,
                outcome=LlmCallOutcome.SUCCESS,
            )
            return primary_result.model_copy(
                update={"llm_metrics": [*primary_result.llm_metrics, metric]}
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error_type = type(exc).__name__
            metric = (
                record_llm_call(
                    stage="relevance_scoring",
                    model=self.model,
                    item_count=len(papers),
                    started_at=started_at,
                    timeout_seconds=self.timeout_seconds,
                    outcome=LlmCallOutcome.FALLBACK,
                    error_type=error_type,
                )
                if self.timeout_seconds is not None and papers
                else None
            )
            logger.warning(
                "Primary relevance scorer failed; using fallback: {}",
                error_type,
            )
            fallback_result = await self.fallback.score_many(
                request,
                search_queries,
                papers,
            )

            warnings = [
                *fallback_result.warnings,
                (
                    f"Primary relevance scorer failed ({error_type}); "
                    "rule-based fallback was used"
                ),
            ]

            return fallback_result.model_copy(
                update={
                    "warnings": list(dict.fromkeys(warnings)),
                    "llm_metrics": [
                        *fallback_result.llm_metrics,
                        *([metric] if metric is not None else []),
                    ],
                }
            )


class ShortlistingPaperRelevanceScorer:
    """封装 ShortlistingPaperRelevanceScorer 相关的数据和行为。"""
    def __init__(
        self,
        prefilter_scorer: PaperRelevanceScorer,
        shortlist_scorer: PaperRelevanceScorer,
        max_shortlist_size: int = MAX_SEMANTIC_SHORTLIST_SIZE,
    ) -> None:
        """初始化当前对象。"""
        if max_shortlist_size < 1:
            raise ValueError(
                "max_shortlist_size must be at least 1"
            )

        self.prefilter_scorer = prefilter_scorer
        self.shortlist_scorer = shortlist_scorer
        self.max_shortlist_size = max_shortlist_size

    async def score_many(
        self,
        request: SearchRequest,
        search_queries: Sequence[str],
        papers: Sequence[PaperSearchResult],
    ) -> PaperRelevanceResult:
        """评分全部输入并按可信度排序。"""
        if not papers:
            return PaperRelevanceResult()

        if len(papers) <= self.max_shortlist_size:
            return await self.shortlist_scorer.score_many(
                request,
                search_queries,
                papers,
            )
        prefilter_result = await self.prefilter_scorer.score_many(
            request,
            search_queries,
            papers,
        )
        rule_score_dict = {
            (assessment.source, assessment.source_id): assessment.score
            for assessment in prefilter_result.assessments
        }

        sorted_papers = sorted(
            papers,
            key=lambda paper: (
                rule_score_dict.get((paper.source, paper.source_id), 0.0),
                paper.cited_by_count,
            ),
            reverse=True,
        )

        shortlisted_papers = sorted_papers[:self.max_shortlist_size]

        shortlist_result = await self.shortlist_scorer.score_many(
            request,
            search_queries,
            shortlisted_papers,
        )

        prefilter_assessments = {
            (assessment.source, assessment.source_id): assessment
            for assessment in prefilter_result.assessments
        }

        shortlist_assessments = {
            (assessment.source, assessment.source_id): assessment
            for assessment in shortlist_result.assessments
        }

        merged_assessments: list[PaperRelevanceAssessment] = []

        for paper in papers:
            identity = (paper.source, paper.source_id)

            assessment = shortlist_assessments.get(
                identity,
                prefilter_assessments.get(identity),
            )

            if assessment is not None:
                merged_assessments.append(assessment)

        warnings = [
            *prefilter_result.warnings,
            *shortlist_result.warnings,
        ]

        return PaperRelevanceResult(
            assessments=merged_assessments,
            warnings=list(dict.fromkeys(warnings)),
            llm_metrics=[
                *prefilter_result.llm_metrics,
                *shortlist_result.llm_metrics,
            ],
        )
