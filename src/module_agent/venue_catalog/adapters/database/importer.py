from __future__ import annotations

from collections.abc import Sequence
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import TypeAlias

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from module_agent.venue_catalog.domain.models import VenueType
from module_agent.venue_catalog.adapters.database.models import (
    VenueAliasModel,
    VenueModel,
    VenueRankingModel,
)
from module_agent.venue_catalog.adapters.rankings.ccf import CCFVenueRecord, normalize_name
from module_agent.venue_catalog.adapters.rankings.icore import (
    ICORE_RANKING_SYSTEM,
    ICOREVenueRecord,
)


VenueCatalogRecord: TypeAlias = CCFVenueRecord | ICOREVenueRecord


@dataclass(slots=True)
class VenueCatalogImportStats:
    """封装 VenueCatalogImportStats 相关的数据和行为。"""
    # 读取到的外部评级记录数。
    source_records: int = 0
    # 新建的会议期刊数量。
    venues_created: int = 0
    # 更新的会议期刊数量。
    venues_updated: int = 0
    # 新建的别名数量。
    aliases_created: int = 0
    # 新建的评级数量。
    rankings_created: int = 0
    # 更新的评级数量。
    rankings_updated: int = 0


@dataclass(slots=True)
class _MergedVenue:
    """封装 _MergedVenue 相关的数据和行为。"""
    # 会议或期刊标准名称。
    canonical_name: str
    # 会议或期刊类型。
    venue_type: VenueType
    # 可用于匹配的别名。
    aliases: dict[str, str] = field(default_factory=dict)
    # 会议期刊评级列表。
    rankings: dict[tuple[str, int, str], VenueCatalogRecord] = field(
        default_factory=dict
    )


async def import_ccf_catalog(
    session: AsyncSession,
    records: list[CCFVenueRecord],
) -> VenueCatalogImportStats:
    """导入外部数据。"""
    return await _import_catalog(
        session,
        records,
        ranking_system="ccf",
        match_existing_aliases=False,
    )


async def import_icore_catalog(
    session: AsyncSession,
    records: list[ICOREVenueRecord],
) -> VenueCatalogImportStats:
    """导入外部数据。"""
    return await _import_catalog(
        session,
        records,
        ranking_system=ICORE_RANKING_SYSTEM,
        match_existing_aliases=True,
    )


async def _import_catalog(
    session: AsyncSession,
    records: Sequence[VenueCatalogRecord],
    *,
    ranking_system: str,
    match_existing_aliases: bool,
) -> VenueCatalogImportStats:
    stats = VenueCatalogImportStats(source_records=len(records))
    merged_venues = _merge_records(records, ranking_system=ranking_system)

    result = await session.execute(
        select(VenueModel).options(
            selectinload(VenueModel.aliases),
            selectinload(VenueModel.rankings),
        )
    )
    existing_venues = result.scalars().unique().all()
    existing_by_name_and_type = {
        (venue.normalized_name, venue.venue_type): venue
        for venue in existing_venues
    }
    existing_by_alias_and_type: dict[
        tuple[str, VenueType], list[VenueModel]
    ] = defaultdict(list)
    for venue in existing_venues:
        for alias in venue.aliases:
            existing_by_alias_and_type[
                (alias.normalized_alias, venue.venue_type)
            ].append(venue)

    incoming_alias_counts = Counter(
        (normalized_alias, merged.venue_type)
        for merged in merged_venues.values()
        for normalized_alias in merged.aliases
    )

    for (normalized_name, venue_type), merged in merged_venues.items():
        venue_model = existing_by_name_and_type.get((normalized_name, venue_type))
        matched_by_alias = False
        if venue_model is None and match_existing_aliases:
            candidates: dict[int, VenueModel] = {}
            for candidate in existing_by_alias_and_type.get(
                (normalized_name, venue_type), []
            ):
                candidates[id(candidate)] = candidate
            for normalized_alias in merged.aliases:
                alias_key = (normalized_alias, venue_type)
                if incoming_alias_counts[alias_key] != 1:
                    continue
                for candidate in existing_by_alias_and_type.get(alias_key, []):
                    candidates[id(candidate)] = candidate
            attachable_candidates = [
                candidate
                for candidate in candidates.values()
                if _can_attach_rankings(candidate, merged.rankings)
            ]
            if len(attachable_candidates) == 1:
                venue_model = attachable_candidates[0]
                matched_by_alias = True

        if venue_model is None:
            venue_model = VenueModel(
                canonical_name=merged.canonical_name,
                normalized_name=normalized_name,
                venue_type=merged.venue_type,
            )
            session.add(venue_model)
            existing_by_name_and_type[(normalized_name, venue_type)] = venue_model
            stats.venues_created += 1
        else:
            if venue_model.venue_type != merged.venue_type:
                raise ValueError(
                    f"Venue type conflict for {merged.canonical_name}: "
                    f"{venue_model.venue_type} != {merged.venue_type}"
                )
            if (
                not matched_by_alias
                and ranking_system == "ccf"
                and venue_model.canonical_name != merged.canonical_name
            ):
                venue_model.canonical_name = merged.canonical_name
                stats.venues_updated += 1

        if matched_by_alias and normalized_name != venue_model.normalized_name:
            merged.aliases.setdefault(normalized_name, merged.canonical_name)

        existing_aliases = {
            alias.normalized_alias for alias in venue_model.aliases
        }
        for normalized_alias, alias in merged.aliases.items():
            if normalized_alias in existing_aliases:
                continue
            venue_model.aliases.append(
                VenueAliasModel(
                    alias=alias,
                    normalized_alias=normalized_alias,
                )
            )
            existing_aliases.add(normalized_alias)
            existing_by_alias_and_type[
                (normalized_alias, venue_type)
            ].append(venue_model)
            stats.aliases_created += 1

        existing_rankings = {
            (
                ranking.ranking_system.casefold(),
                ranking.edition_year,
                ranking.category or "",
            ): ranking
            for ranking in venue_model.rankings
        }
        for ranking_key, record in merged.rankings.items():
            ranking_model = existing_rankings.get(ranking_key)
            if ranking_model is None:
                venue_model.rankings.append(
                    VenueRankingModel(
                        ranking_system=ranking_system,
                        level=record.level,
                        edition_year=record.edition_year,
                        category=record.category,
                        source_url=record.source_url,
                    )
                )
                stats.rankings_created += 1
            else:
                if (
                    ranking_model.level != record.level
                    or ranking_model.source_url != record.source_url
                ):
                    ranking_model.level = record.level
                    ranking_model.source_url = record.source_url
                    stats.rankings_updated += 1

    await session.flush()
    return stats


def _can_attach_rankings(
    venue: VenueModel,
    rankings: dict[tuple[str, int, str], VenueCatalogRecord],
) -> bool:
    existing_rankings = {
        (
            ranking.ranking_system.casefold(),
            ranking.edition_year,
            ranking.category or "",
        ): ranking
        for ranking in venue.rankings
    }
    for ranking_key, record in rankings.items():
        existing = existing_rankings.get(ranking_key)
        if existing is not None and existing.source_url != record.source_url:
            return False
    return True


def _merge_records(
    records: Sequence[VenueCatalogRecord],
    *,
    ranking_system: str = "ccf",
) -> dict[tuple[str, VenueType], _MergedVenue]:
    merged: dict[tuple[str, VenueType], _MergedVenue] = {}
    for record in records:
        normalized_name = normalize_name(record.canonical_name)
        venue_key = (normalized_name, record.venue_type)
        venue = merged.get(venue_key)
        if venue is None:
            venue = _MergedVenue(
                canonical_name=record.canonical_name,
                venue_type=record.venue_type,
            )
            merged[venue_key] = venue

        for alias in record.aliases:
            normalized_alias = normalize_name(alias)
            if normalized_alias and normalized_alias != normalized_name:
                venue.aliases.setdefault(normalized_alias, alias)

        ranking_key = (
            ranking_system.casefold(),
            record.edition_year,
            record.category,
        )
        existing_ranking = venue.rankings.get(ranking_key)
        if existing_ranking and existing_ranking.level != record.level:
            raise ValueError(
                f"Conflicting {ranking_system} levels for {record.canonical_name} "
                f"in {record.category}"
            )
        venue.rankings[ranking_key] = record

    return merged
