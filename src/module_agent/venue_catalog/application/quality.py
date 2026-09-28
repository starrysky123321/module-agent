from module_agent.venue_catalog.domain.repository import VenueRepository
from module_agent.literature.domain.search import VenueQualityRequirement
from module_agent.venue_catalog.domain.models import Venue
from module_agent.venue_catalog.application.name_resolver import generate_venue_name_candidates
from module_agent.venue_catalog.domain.cache import VenueCache

class VenueQualityService:
    """封装相关应用用例。"""
    def __init__(self, repository: VenueRepository, cache: VenueCache | None = None) -> None:
        """初始化当前对象。"""
        self.repository = repository
        self.cache = cache

    async def resolve_venue(self, name: str | None) -> Venue | None:
        """解析并返回匹配结果。"""
        candidates = generate_venue_name_candidates(name)
        
        if self.cache is not None:
            for candidate in candidates:
                cached_venue = await self.cache.get(candidate)
                if cached_venue is not None:
                    return cached_venue
        
        for candidate in candidates:
            venue = await self.repository.get_by_name(candidate)
            if venue is None:
                continue
            
            if self.cache is not None:
                for cache_name in candidates:
                    await self.cache.set(cache_name, venue)
            
            return venue

        return None

    async def matches_requirement(
        self,
        venue_name: str | None,
        requirement: VenueQualityRequirement | None,
    ) -> bool:
        """判断会议期刊是否满足评级要求。"""
        if requirement is None:
            return True

        normalized_ranking_system = " ".join(
            requirement.ranking_system.casefold().split()
        )
        normalized_allowed_levels = {
            " ".join(level.casefold().split())
            for level in requirement.allowed_levels
            if level.strip()
        }

        venue = await self.resolve_venue(venue_name)
        if venue is None:
            return False

        matching_rankings = [
            ranking
            for ranking in venue.rankings
            if " ".join(ranking.ranking_system.casefold().split())
            == normalized_ranking_system
        ]
        
        if not matching_rankings:
            return False

        latest_year = max(ranking.edition_year for ranking in matching_rankings)

        return any(
            ranking.edition_year == latest_year
            and " ".join(ranking.level.casefold().split())
                in normalized_allowed_levels
            for ranking in matching_rankings
        )

    async def matches_requested_venues(
        self,
        paper_venue: str | None,
        requested_venues: list[str],
    ) -> bool:
        """判断论文场所是否属于用户指定范围。"""
        if not requested_venues:
            return True

        if paper_venue is None or not paper_venue.strip():
            return False

        normalized_paper_venue = " ".join(paper_venue.casefold().split())
        normalized_requested_venues = {
            " ".join(venue.casefold().split())
            for venue in requested_venues
            if venue.strip()
        }
        if normalized_paper_venue in normalized_requested_venues:
            return True

        resolved_paper_venue = await self.resolve_venue(paper_venue)
        if resolved_paper_venue is None:
            return False

        for requested_venue in requested_venues:
            resolved_requested_venue = await self.resolve_venue(requested_venue)
            if resolved_requested_venue is None:
                continue
            if (
                resolved_paper_venue.id is not None
                and resolved_paper_venue.id == resolved_requested_venue.id
            ):
                return True
        return False
        
