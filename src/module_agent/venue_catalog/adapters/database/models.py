from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from module_agent.venue_catalog.domain.models import VenueType
from module_agent.shared.database.base import Base


class VenueModel(Base):
    """映射数据库中的持久化记录。"""
    __tablename__ = "venues"
    __table_args__ = (
        UniqueConstraint(
            "normalized_name",
            "venue_type",
            name="uq_venue_name_type",
        ),
        Index("ix_venues_normalized_name", "normalized_name"),
    )

    # 记录主键。
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    # 会议或期刊标准名称。
    canonical_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    # 规范化后的会议期刊名称。
    normalized_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    # 会议或期刊类型。
    venue_type: Mapped[VenueType] = mapped_column(
        SAEnum(
            VenueType,
            name="venue_type",
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
    )

    # 可用于匹配的别名。
    aliases: Mapped[list[VenueAliasModel]] = relationship(
        back_populates="venue",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    # 会议期刊评级列表。
    rankings: Mapped[list[VenueRankingModel]] = relationship(
        back_populates="venue",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class VenueAliasModel(Base):
    """映射数据库中的持久化记录。"""
    __tablename__ = "venue_aliases"
    __table_args__ = (
        UniqueConstraint(
            "venue_id",
            "normalized_alias",
            name="uq_venue_alias_per_venue",
        ),
        Index("ix_venue_aliases_normalized_alias", "normalized_alias"),
    )

    # 记录主键。
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    # 关联的会议或期刊 ID。
    venue_id: Mapped[int] = mapped_column(
        ForeignKey("venues.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 会议或期刊别名。
    alias: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    # 规范化后的别名。
    normalized_alias: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    # 论文发表的会议或期刊。
    venue: Mapped[VenueModel] = relationship(back_populates="aliases")


class VenueRankingModel(Base):
    """映射数据库中的持久化记录。"""
    __tablename__ = "venue_rankings"
    __table_args__ = (
        UniqueConstraint(
            "venue_id",
            "ranking_system",
            "edition_year",
            "category",
            name="uq_venue_ranking_edition_category",
            postgresql_nulls_not_distinct=True,
        ),
    )

    # 记录主键。
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    # 关联的会议或期刊 ID。
    venue_id: Mapped[int] = mapped_column(
        ForeignKey("venues.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 评级体系名称。
    ranking_system: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    # 评级或严重程度。
    level: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    # 评级版本年份。
    edition_year: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    # 评级所属研究领域。
    category: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    # 评级数据来源页面。
    source_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # 论文发表的会议或期刊。
    venue: Mapped[VenueModel] = relationship(back_populates="rankings")
