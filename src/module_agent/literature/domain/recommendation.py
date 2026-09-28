from typing import Annotated

from pydantic import BaseModel, Field

from module_agent.literature.domain.paper import Paper
from module_agent.literature.domain.method import PaperMethodProfile



class LiteratureRunPaper(BaseModel):
    """Run-specific ranking metadata stored on the run-paper association."""

    # 关联的论文 ID。
    paper_id: Annotated[int, Field(gt=0)]
    # 论文在本次推荐中的顺序。
    position: Annotated[int, Field(ge=0)]
    # 论文与用户需求的相关性分数。
    relevance_score: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    # 相关性评分的解释。
    relevance_reason: str = ""
    # 匹配到的检索词。
    matched_terms: list[str] = Field(default_factory=list)
    # Literature Agent 提取的方法画像。
    method_profile: PaperMethodProfile | None = None


class LiteraturePaperRecommendation(Paper):
    """A paper together with its ranking evidence for one literature run."""

    # 论文在本次推荐中的顺序。
    position: Annotated[int, Field(ge=0)]
    # 论文与用户需求的相关性分数。
    relevance_score: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    # 相关性评分的解释。
    relevance_reason: str = ""
    # 匹配到的检索词。
    matched_terms: list[str] = Field(default_factory=list)
    # Literature Agent 提取的方法画像。
    method_profile: PaperMethodProfile | None = None
