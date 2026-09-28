from pydantic import BaseModel, Field
from enum import StrEnum

class VenueType(StrEnum):
    """封装 VenueType 相关的数据和行为。"""
    CONFERENCE = "conference"
    JOURNAL = "journal"


class VenueRanking(BaseModel):
    """封装 VenueRanking 相关的数据和行为。"""
    # 评级体系名称。
    ranking_system: str = Field(min_length=1)     # ccf、core、jcr
    # 评级或严重程度。
    level: str = Field(min_length=1)             # A、A*、Q1
    # 评级版本年份。
    edition_year: int       # 评级版本年份
    # 评级所属研究领域。
    category: str | None = None    # 所属领域，可选
    # 评级数据来源页面。
    source_url: str | None = None  # 数据来源，可选
    

class Venue(BaseModel):
    """封装 Venue 相关的数据和行为。"""
    # 记录主键。
    id: int | None = None
    # 会议或期刊标准名称。
    canonical_name: str = Field(min_length=1)
    # 会议或期刊类型。
    venue_type: VenueType
    # 可用于匹配的别名。
    aliases: list[str] = Field(default_factory=list)
    # 会议期刊评级列表。
    rankings: list[VenueRanking] = Field(default_factory=list)
