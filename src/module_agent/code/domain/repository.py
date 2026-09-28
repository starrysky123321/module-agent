from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, HttpUrl, StringConstraints


NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class RepositoryOrigin(StrEnum):
    """仓库与论文之间的归属关系。"""

    # 论文直接提供的官方仓库。
    OFFICIAL = "official"
    # 论文作者账号下的可信仓库。
    AUTHOR = "author"
    # 与作者无直接关系的第三方实现。
    THIRD_PARTY = "third_party"
    # 现有证据不足以判断来源。
    UNKNOWN = "unknown"


class RepositoryEvidenceType(StrEnum):
    """用于判断仓库可信度的证据类型。"""

    # 论文页面或正文直接给出的仓库链接。
    PAPER_URL = "paper_url"
    # 仓库内容包含论文 DOI。
    DOI = "doi"
    # 仓库内容包含完整论文标题。
    TITLE = "title"
    # 仓库以引用形式提及论文。
    CITATION = "citation"
    # 仓库所有者与论文作者匹配。
    AUTHOR = "author"
    # 仓库内容覆盖部分论文关键词。
    KEYWORD = "keyword"


class RepositoryEvidence(BaseModel):
    """一条可解释的仓库匹配证据。"""

    # 证据种类。
    evidence_type: RepositoryEvidenceType
    # 面向用户的证据说明。
    description: NonEmptyText
    # 该证据对总置信度的贡献。
    weight: Annotated[float, Field(ge=0.0, le=1.0)]
    # 证据来源页面。
    source_url: HttpUrl | None = None


class RepositoryCandidate(BaseModel):
    """等待评分和选择的代码仓库候选。"""

    # 仓库托管平台。
    provider: NonEmptyText = "github"
    # 平台内的 owner/repository 名称。
    full_name: NonEmptyText
    # 可用于拉取仓库的 HTTPS 地址。
    repository_url: HttpUrl
    # 仓库所有者账号。
    owner_login: NonEmptyText
    # 仓库简介，用于论文匹配。
    description: str | None = None
    # 仓库主题标签。
    topics: list[str] = Field(default_factory=list)
    # README 文本，只用于评分，不写入持久化输出。
    readme_text: str | None = Field(default=None, exclude=True)
    # 仓库默认分支。
    default_branch: str | None = None
    # 仓库是否已经归档。
    archived: bool = False
    # SPDX 许可证标识。
    license_spdx: str | None = None
    # 评分后判断出的仓库来源。
    origin: RepositoryOrigin = RepositoryOrigin.UNKNOWN
    # 证据累计得到的可信度。
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    # 支撑来源和可信度判断的证据。
    evidence: list[RepositoryEvidence] = Field(default_factory=list)
