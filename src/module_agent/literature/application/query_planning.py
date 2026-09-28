import asyncio
import time

from module_agent.literature.domain.search import SearchRequest
from module_agent.literature.domain.llm_metric import LlmCallOutcome
from module_agent.literature.domain.query import LiteratureQueryPlan
from module_agent.literature.domain.query import LiteratureQueryPlanner
from module_agent.literature.domain.query import MAX_SEARCH_QUERIES
from module_agent.literature.application.llm_observability import (
    record_llm_call,
    validate_timeout_seconds,
)

class RuleBasedLiteratureQueryPlanner:
    """封装 RuleBasedLiteratureQueryPlanner 相关的数据和行为。"""
    async def plan(
        self,
        request: SearchRequest,
    ) -> LiteratureQueryPlan:
        # 清理首尾空格，并把连续空白压缩成一个空格
        """生成当前阶段的结构化计划。"""
        topic = " ".join(request.topic.split())

        # 第一条始终是topic
        search_queries: list[str] = [topic]

        # 使用casefold后的值进行大小写无关去重
        seen: set[str] = {topic.casefold()}

        for raw_keyword in request.keywords:
            if len(search_queries) >= MAX_SEARCH_QUERIES:
                break

            keyword = " ".join(raw_keyword.split())

            # 跳过空关键词
            if not keyword:
                continue

            # 跳过与topic相同的关键词
            if keyword.casefold() == topic.casefold():
                continue

            candidate = f"{topic} {keyword}"
            candidate_key = candidate.casefold()

            # 跳过重复查询
            if candidate_key in seen:
                continue

            search_queries.append(candidate)
            seen.add(candidate_key)

        return LiteratureQueryPlan(
            search_queries=search_queries,
        )
        
        
class FallbackLiteratureQueryPlanner:
    """封装 FallbackLiteratureQueryPlanner 相关的数据和行为。"""
    def __init__(
        self,
        primary: LiteratureQueryPlanner,
        fallback: LiteratureQueryPlanner,
        *,
        timeout_seconds: float | None = None,
        model: str = "unknown",
    ):
        """初始化当前对象。"""
        validate_timeout_seconds(timeout_seconds)
        self.primary = primary
        self.fallback = fallback
        self.timeout_seconds = timeout_seconds
        self.model = model
        
    async def plan(self, request: SearchRequest) -> LiteratureQueryPlan:
        """生成当前阶段的结构化计划。"""
        started_at = time.perf_counter()
        try:
            if self.timeout_seconds is None:
                return await self.primary.plan(request)
            async with asyncio.timeout(self.timeout_seconds):
                primary_plan = await self.primary.plan(request)
            metric = record_llm_call(
                stage="query_planning",
                model=self.model,
                item_count=1,
                started_at=started_at,
                timeout_seconds=self.timeout_seconds,
                outcome=LlmCallOutcome.SUCCESS,
            )
            return primary_plan.model_copy(
                update={"llm_metrics": [*primary_plan.llm_metrics, metric]}
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            metric = (
                record_llm_call(
                    stage="query_planning",
                    model=self.model,
                    item_count=1,
                    started_at=started_at,
                    timeout_seconds=self.timeout_seconds,
                    outcome=LlmCallOutcome.FALLBACK,
                    error_type=type(exc).__name__,
                )
                if self.timeout_seconds is not None
                else None
            )
            fallback_plan = await self.fallback.plan(request)

            warnings = [
                *fallback_plan.warnings,
                "Primary query planner failed; fallback query planner was used",
            ]
            warnings = list(dict.fromkeys(warnings))

            return fallback_plan.model_copy(
                update={
                    "warnings": warnings,
                    "llm_metrics": [
                        *fallback_plan.llm_metrics,
                        *([metric] if metric is not None else []),
                    ],
                },
            )
