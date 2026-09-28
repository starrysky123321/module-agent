from typing import Protocol
from module_agent.literature.domain.search import SearchRequest
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints
from module_agent.literature.domain.llm_metric import LlmCallMetric

MAX_SEARCH_QUERIES = 5


SearchQuery = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=500,
    ),
]


class LiteratureQueryPlan(BaseModel):
    """封装 LiteratureQueryPlan 相关的数据和行为。"""
    # 本次实际使用的检索词。
    search_queries: Annotated[
        list[SearchQuery],
        Field(
            min_length=1,
            max_length=MAX_SEARCH_QUERIES,
        ),
    ]
    # 不阻断流程的警告列表。
    warnings: list[str] = Field(default_factory=list)
    # 各阶段模型调用指标。
    llm_metrics: list[LlmCallMetric] = Field(default_factory=list)
      
      
class LiteratureQueryPlanner(Protocol):
    """封装 LiteratureQueryPlanner 相关的数据和行为。"""
    async def plan(
        self,
        request: SearchRequest,
    ) -> LiteratureQueryPlan:
        """生成当前阶段的结构化计划。"""
        ...
