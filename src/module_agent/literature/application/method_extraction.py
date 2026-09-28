from module_agent.literature.domain.method import PaperMethodExtractor, PaperMethodExtractionResult
from module_agent.literature.domain.search import PaperSearchResult, SearchRequest
from collections.abc import Sequence
import asyncio
import time
from module_agent.literature.domain.method import PaperMethodProfile
from module_agent.literature.domain.llm_metric import LlmCallOutcome
from module_agent.literature.application.llm_observability import (
    record_llm_call,
    validate_timeout_seconds,
)



class FallbackPaperMethodExtractor:
    """封装 FallbackPaperMethodExtractor 相关的数据和行为。"""
    def __init__(
        self,
        primary: PaperMethodExtractor,
        *,
        timeout_seconds: float | None = None,
        model: str = "unknown",
    ) -> None:
        """初始化当前对象。"""
        validate_timeout_seconds(timeout_seconds)
        self.primary = primary
        self.timeout_seconds = timeout_seconds
        self.model = model
        
        
    async def extract_many(
        self,
        request: SearchRequest,
        papers: Sequence[PaperSearchResult],
    ) -> PaperMethodExtractionResult:
        
        """批量提取结构化信息。"""
        if not papers:
            return PaperMethodExtractionResult()
        
        started_at = time.perf_counter()
        try:
            if self.timeout_seconds is None:
                return await self.primary.extract_many(request, papers)
            async with asyncio.timeout(self.timeout_seconds):
                primary_result = await self.primary.extract_many(request, papers)
            metric = record_llm_call(
                stage="method_extraction",
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
            metric = (
                record_llm_call(
                    stage="method_extraction",
                    model=self.model,
                    item_count=len(papers),
                    started_at=started_at,
                    timeout_seconds=self.timeout_seconds,
                    outcome=LlmCallOutcome.FALLBACK,
                    error_type=type(exc).__name__,
                )
                if self.timeout_seconds is not None
                else None
            )
            profiles = []
            for paper in papers:
                profiles.append(
                    PaperMethodProfile(
                        source=paper.source,
                        source_id=paper.source_id,
                        confidence=0.0,
                    )
                )

            warnings=[f"Paper method extraction failed ({type(exc).__name__}); " "unknown profiles were used"]
            return PaperMethodExtractionResult(
                profiles=profiles,
                warnings=warnings,
                llm_metrics=[metric] if metric is not None else [],
            )


class BatchedPaperMethodExtractor:
    """封装 BatchedPaperMethodExtractor 相关的数据和行为。"""
    def __init__(
        self,
        inner: PaperMethodExtractor,
        batch_size: int = 10,
    ) -> None:
        """初始化当前对象。"""
        self.inner = inner
        if not 1 <= batch_size <= 10:
            raise ValueError("Batch size must be between 1 and 10")
        self.batch_size = batch_size
        
    async def extract_many(
        self,
        request: SearchRequest,
        papers: Sequence[PaperSearchResult],
    ) -> PaperMethodExtractionResult:
        
        """批量提取结构化信息。"""
        if not papers:
            return PaperMethodExtractionResult()
        
        profiles = []
        warnings = []
        llm_metrics = []
        
        for start in range(0, len(papers), self.batch_size):
            end = min(start + self.batch_size, len(papers))
            batch = papers[start:end]
            
            result = await self.inner.extract_many(request, batch)

            expected_ids = [
                (paper.source, paper.source_id)
                for paper in batch
            ]
            actual_ids = [
                (profile.source, profile.source_id)
                for profile in result.profiles
            ]
            if (
                len(actual_ids) != len(expected_ids)
                or len(set(actual_ids)) != len(actual_ids)
                or set(actual_ids) != set(expected_ids)
            ):
                raise ValueError(
                    "Inner method profiles do not match batch papers"
                )
            
            profiles_by_id = {
                (profile.source, profile.source_id): profile
                for profile in result.profiles
            }

            for paper in batch:
                profiles.append(
                    profiles_by_id[(paper.source, paper.source_id)]
                )
            
            warnings.extend(result.warnings)
            llm_metrics.extend(result.llm_metrics)
        
        warnings = list(dict.fromkeys(warnings))
        
        return PaperMethodExtractionResult(
            profiles=profiles,
            warnings=warnings,
            llm_metrics=llm_metrics,
        )
            
            
            
