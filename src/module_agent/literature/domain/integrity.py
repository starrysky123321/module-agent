"""论文撤稿信息的证据快照；未发现标记不等于论文有效性保证。"""

from datetime import datetime, timezone
from enum import StrEnum
from html import unescape
import re
from typing import Protocol

from pydantic import BaseModel, Field


class PaperIntegrityStatus(StrEnum):
    UNKNOWN = "unknown"
    NOT_FLAGGED = "not_flagged"
    RETRACTED = "retracted"
    NOTICE = "notice"


class PaperIntegrity(BaseModel):
    # 本次元数据核验结果，不表示实验正确性。
    status: PaperIntegrityStatus = PaperIntegrityStatus.UNKNOWN
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # 提供状态的元数据来源。
    sources: list[str] = Field(default_factory=list)
    # 支持判断的原始字段说明或标题。
    evidence: list[str] = Field(default_factory=list)
    # 核验失败或覆盖范围限制。
    warnings: list[str] = Field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.status in {
            PaperIntegrityStatus.RETRACTED,
            PaperIntegrityStatus.NOTICE,
        }


class PaperIntegrityChecker(Protocol):
    async def check(self, doi: str | None, title: str) -> PaperIntegrity:
        """核对单篇论文；网络失败必须保留 unknown。"""
        ...


def title_integrity(title: str, source: str) -> PaperIntegrity | None:
    """只识别明确的标题前缀，避免误伤研究撤稿现象的正常论文。"""
    plain = unescape(re.sub(r"<[^>]*>", "", title)).strip()
    if re.match(
        r"^(?:\[\s*retracted\s*\]|retracted\s*[:\-–—]|已撤稿\s*[:：])", plain, re.I
    ):
        status = PaperIntegrityStatus.RETRACTED
    elif re.match(
        r"^(?:retraction(?:\s+(?:note|notice))?\s*[:\-–—]|撤稿声明\s*[:：])",
        plain,
        re.I,
    ):
        status = PaperIntegrityStatus.NOTICE
    else:
        return None
    return PaperIntegrity(status=status, sources=[source], evidence=[plain])


def merge_integrity(*facts: PaperIntegrity | None) -> PaperIntegrity:
    """多来源合并时保留风险较高的结论，不用未发现标记覆盖撤稿证据。"""
    present = [fact for fact in facts if fact is not None]
    priority = {
        PaperIntegrityStatus.UNKNOWN: 0,
        PaperIntegrityStatus.NOT_FLAGGED: 1,
        PaperIntegrityStatus.NOTICE: 2,
        PaperIntegrityStatus.RETRACTED: 3,
    }
    return PaperIntegrity(
        status=max(
            (fact.status for fact in present),
            key=priority.__getitem__,
            default=PaperIntegrityStatus.UNKNOWN,
        ),
        sources=list(
            dict.fromkeys(source for fact in present for source in fact.sources)
        ),
        evidence=list(
            dict.fromkeys(item for fact in present for item in fact.evidence)
        ),
        warnings=list(
            dict.fromkeys(item for fact in present for item in fact.warnings)
        ),
    )
