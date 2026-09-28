import asyncio
import time

from module_agent.shared.exceptions import LiteratureSourceSkippedError
from module_agent.literature.domain.search import (
    PaperSearchResult,
    SearchRequest,
    SearchResponse,
    SourceSearchMetric,
    SourceSearchOutcome,
)
from module_agent.literature.domain.source import LiteratureSource


class LiteratureSearchService:
    """封装相关应用用例。"""
    def __init__(self, sources: list[LiteratureSource]) -> None:
        """初始化当前对象。"""
        self.sources = sources

    async def search(self, request: SearchRequest) -> SearchResponse:
        """搜索符合条件的结果。"""
        executions = await asyncio.gather(
            *(self._execute_source(source, request) for source in self.sources),
        )

        results: list[PaperSearchResult] = []
        warnings: list[str] = []
        failures: list[Exception] = []
        source_metrics: list[SourceSearchMetric] = []

        for batch, metric in executions:
            source_metrics.append(metric)

            if isinstance(batch, Exception):
                failures.append(batch)
                action = (
                    "skipped"
                    if metric.outcome is SourceSearchOutcome.SKIPPED
                    else "failed"
                )
                warning = (
                    f"{metric.source} {action}: "
                    f"{type(batch).__name__}: "
                    f"{batch}"
                )
                warnings.append(warning)
                continue

            results.extend(batch)

        if self.sources and len(failures) == len(self.sources):
            raise failures[0]

        return SearchResponse(
            results=results,
            warnings=warnings,
            source_metrics=source_metrics,
        )

    @staticmethod
    async def _execute_source(
        source: LiteratureSource,
        request: SearchRequest,
    ) -> tuple[list[PaperSearchResult] | Exception, SourceSearchMetric]:
        source_name = getattr(
            source,
            "__name__",
            source.__class__.__name__,
        )
        started_at = time.perf_counter()

        try:
            results = await source(request)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            duration_ms = max(0.0, (time.perf_counter() - started_at) * 1000)
            return exc, SourceSearchMetric(
                source=source_name,
                query=request.topic,
                duration_ms=duration_ms,
                result_count=0,
                outcome=(
                    SourceSearchOutcome.SKIPPED
                    if isinstance(exc, LiteratureSourceSkippedError)
                    else SourceSearchOutcome.FAILED
                ),
                error_type=type(exc).__name__,
            )

        duration_ms = max(0.0, (time.perf_counter() - started_at) * 1000)
        return results, SourceSearchMetric(
            source=source_name,
            query=request.topic,
            duration_ms=duration_ms,
            result_count=len(results),
            outcome=SourceSearchOutcome.SUCCESS,
        )
