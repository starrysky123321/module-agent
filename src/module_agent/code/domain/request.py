from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from module_agent.literature.domain.method import PaperMethodProfile


NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class CodePaperInput(BaseModel):
    """Code Agent 处理一篇已选论文所需的稳定输入。"""

    # 数据库中的论文主键，用于关联产物。
    paper_id: Annotated[int, Field(gt=0)]
    # 论文来自哪个检索平台。
    source: NonEmptyText
    # 论文在检索平台中的唯一标识。
    source_id: NonEmptyText
    # 论文标题，用于仓库搜索和匹配。
    title: NonEmptyText
    # 作者姓名，用于识别作者仓库。
    authors: list[str] = Field(default_factory=list)
    # DOI，用于验证仓库与论文的对应关系。
    doi: str | None = None
    # 摘要，为复现计划提供方法上下文。
    abstract: str | None = None
    # 论文落地页，用于寻找直接代码链接。
    landing_page_url: str | None = None
    # Literature Agent 提取的方法画像。
    method_profile: PaperMethodProfile | None = None
    # 论文 PDF 地址，用于从正文提取代码仓库链接。
    pdf_url: str | None = None
    # 论文补充材料地址，用于发现额外的官方代码链接。
    supplementary_urls: list[str] = Field(default_factory=list)


class CodeAgentRequest(BaseModel):
    """Workflow 传给 Code Agent 的请求。"""

    # 本次请求关联的 LiteratureRun。
    literature_run_id: Annotated[int, Field(gt=0)]
    # 用户选中的论文，至少一篇且不能重复。
    papers: Annotated[list[CodePaperInput], Field(min_length=1, max_length=20)]
    # 用户对代码产物的补充要求。
    code_requirements: Annotated[str, Field(max_length=5000)] | None = None

    @field_validator("code_requirements", mode="before")
    @classmethod
    def normalize_requirements(cls, value: object) -> object:
        """去掉要求两端空白，并把空字符串转成 None。"""
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @model_validator(mode="after")
    def reject_duplicate_papers(self) -> "CodeAgentRequest":
        """拒绝同一次请求中的重复论文。"""
        paper_ids = [paper.paper_id for paper in self.papers]
        if len(paper_ids) != len(set(paper_ids)):
            raise ValueError("Code Agent papers must have unique paper ids")
        return self
