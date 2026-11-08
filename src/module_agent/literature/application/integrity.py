"""只对推荐短名单核验，限制总耗时和并发，不阻塞整批检索。"""

import asyncio

from module_agent.literature.domain.integrity import (
    PaperIntegrity,
    PaperIntegrityChecker,
    merge_integrity,
    title_integrity,
)
from module_agent.literature.domain.search import PaperSearchResult


class PaperIntegrityService:
    def __init__(
        self,
        checker: PaperIntegrityChecker,
        *,
        budget_seconds: float = 12.0,
        max_papers: int = 20,
    ) -> None:
        if budget_seconds <= 0 or max_papers < 1:
            raise ValueError("Integrity budgets must be positive")
        self.checker = checker
        self.budget_seconds = budget_seconds
        self.max_papers = max_papers

    async def check_many(
        self, papers: list[PaperSearchResult], *, result_limit: int | None = None
    ) -> tuple[list[PaperSearchResult], list[str]]:
        semaphore = asyncio.Semaphore(2)
        facts: dict[int, PaperIntegrity] = {}

        async def check(index: int, paper: PaperSearchResult) -> None:
            async with semaphore:
                try:
                    facts[index] = await self.checker.check(paper.doi, paper.title)
                except Exception as error:
                    facts[index] = PaperIntegrity(
                        warnings=[f"元数据核验失败（{type(error).__name__}）"]
                    )

        tasks = [
            asyncio.create_task(check(index, paper))
            for index, paper in enumerate(papers[: self.max_papers])
        ]
        try:
            if tasks:
                _, pending = await asyncio.wait(tasks, timeout=self.budget_seconds)
                for task in pending:
                    task.cancel()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        result = []
        warnings = []
        unverified = 0
        for index, paper in enumerate(papers):
            fact = facts.get(
                index, PaperIntegrity(warnings=["本轮核验预算已用尽，尚未核验"])
            )
            integrity = merge_integrity(
                paper.integrity, title_integrity(paper.title, paper.source), fact
            )
            if integrity.blocked:
                warnings.append(f"已排除撤稿论文或撤稿声明：{paper.title[:160]}")
                continue
            if result_limit is None or len(result) < result_limit:
                unverified += bool(integrity.warnings)
                result.append(paper.model_copy(update={"integrity": integrity}))
        if unverified:
            warnings.append(
                f"{unverified} 篇论文的撤稿元数据未完整核验；页面未发现标记不代表论文质量或有效性保证。"
            )
        return result, warnings
