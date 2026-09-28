import asyncio

from module_agent.literature.domain.search import VenueQualityRequirement
from module_agent.venue_catalog.domain.models import Venue, VenueRanking, VenueType
from module_agent.venue_catalog.application.quality import VenueQualityService


class FakeVenueRepository:
    def __init__(self, venue: Venue | None) -> None:
        self.venue = venue
        self.requested_names: list[str] = []

    async def get_by_name(self, name: str) -> Venue | None:
        self.requested_names.append(name)
        return self.venue


class FakeVenueCache:
    def __init__(self, values: dict[str, Venue] | None = None) -> None:
        self.values = values or {}
        self.requested_names: list[str] = []
        self.stored_names: list[str] = []

    async def get(self, name: str) -> Venue | None:
        self.requested_names.append(name)
        return self.values.get(name)

    async def set(self, name: str, venue: Venue) -> None:
        self.stored_names.append(name)
        self.values[name] = venue

    async def delete(self, name: str) -> None:
        self.values.pop(name, None)


def quality_requirement(*allowed_levels: str) -> VenueQualityRequirement:
    return VenueQualityRequirement(
        ranking_system=" CCF ",
        allowed_levels=list(allowed_levels),
    )


def test_quality_service_allows_any_venue_without_requirement() -> None:
    repository = FakeVenueRepository(venue=None)
    service = VenueQualityService(repository)

    matches = asyncio.run(service.matches_requirement(None, None))

    assert matches is True
    assert repository.requested_names == []


def test_quality_service_rejects_missing_or_unknown_venue() -> None:
    repository = FakeVenueRepository(venue=None)
    service = VenueQualityService(repository)
    requirement = quality_requirement("A")

    missing = asyncio.run(service.matches_requirement(None, requirement))
    unknown = asyncio.run(service.matches_requirement("Unknown", requirement))

    assert missing is False
    assert unknown is False
    assert repository.requested_names == ["Unknown"]


def test_quality_service_tries_resolved_venue_name_candidates() -> None:
    venue = Venue(
        canonical_name="AAAI Conference on Artificial Intelligence",
        venue_type=VenueType.CONFERENCE,
        rankings=[
            VenueRanking(
                ranking_system="core",
                level="A*",
                edition_year=2026,
            )
        ],
    )

    class CandidateVenueRepository:
        def __init__(self) -> None:
            self.requested_names: list[str] = []

        async def get_by_name(self, name: str) -> Venue | None:
            self.requested_names.append(name)
            if name == "AAAI Conference on Artificial Intelligence":
                return venue
            return None

    repository = CandidateVenueRepository()
    service = VenueQualityService(repository)
    requirement = VenueQualityRequirement(
        ranking_system="core",
        allowed_levels=["A*"],
    )

    matches = asyncio.run(
        service.matches_requirement(
            "Proceedings of the AAAI Conference on Artificial Intelligence",
            requirement,
        )
    )

    assert matches is True
    assert repository.requested_names == [
        "Proceedings of the AAAI Conference on Artificial Intelligence",
        "AAAI Conference on Artificial Intelligence",
    ]


def test_requested_venue_matches_normalized_text_without_database() -> None:
    repository = FakeVenueRepository(venue=None)
    service = VenueQualityService(repository)

    matches = asyncio.run(
        service.matches_requested_venues(
            " Unknown   Conference ",
            ["unknown conference"],
        )
    )

    assert matches is True
    assert repository.requested_names == []


def test_requested_venue_matches_resolved_database_identity() -> None:
    venue = Venue(
        id=42,
        canonical_name="AAAI Conference on Artificial Intelligence",
        venue_type=VenueType.CONFERENCE,
    )

    class MappedVenueRepository:
        def __init__(self) -> None:
            self.requested_names: list[str] = []

        async def get_by_name(self, name: str) -> Venue | None:
            self.requested_names.append(name)
            if name in {
                "AAAI Conference on Artificial Intelligence",
                "AAAI",
            }:
                return venue
            return None

    repository = MappedVenueRepository()
    service = VenueQualityService(repository)

    matches = asyncio.run(
        service.matches_requested_venues(
            "Proceedings of the AAAI Conference on Artificial Intelligence",
            ["AAAI"],
        )
    )

    assert matches is True
    assert repository.requested_names == [
        "Proceedings of the AAAI Conference on Artificial Intelligence",
        "AAAI Conference on Artificial Intelligence",
        "AAAI",
    ]


def test_quality_service_matches_normalized_level() -> None:
    venue = Venue(
        canonical_name="CVPR",
        venue_type=VenueType.CONFERENCE,
        rankings=[
            VenueRanking(
                ranking_system="ccf",
                level="A*",
                edition_year=2025,
            )
        ],
    )
    service = VenueQualityService(FakeVenueRepository(venue))

    matches = asyncio.run(
        service.matches_requirement("CVPR", quality_requirement(" a* "))
    )

    assert matches is True


def test_quality_service_does_not_use_substring_level_matching() -> None:
    venue = Venue(
        canonical_name="Example Conference",
        venue_type=VenueType.CONFERENCE,
        rankings=[
            VenueRanking(
                ranking_system="ccf",
                level="A",
                edition_year=2025,
            )
        ],
    )
    service = VenueQualityService(FakeVenueRepository(venue))

    matches = asyncio.run(
        service.matches_requirement("Example Conference", quality_requirement("A*"))
    )

    assert matches is False


def test_quality_service_uses_only_latest_ranking_edition() -> None:
    venue = Venue(
        canonical_name="Example Journal",
        venue_type=VenueType.JOURNAL,
        rankings=[
            VenueRanking(
                ranking_system="ccf",
                level="A",
                edition_year=2022,
            ),
            VenueRanking(
                ranking_system="ccf",
                level="B",
                edition_year=2025,
            ),
        ],
    )
    service = VenueQualityService(FakeVenueRepository(venue))

    matches = asyncio.run(
        service.matches_requirement("Example Journal", quality_requirement("A"))
    )

    assert matches is False


def test_quality_service_does_not_query_repository_on_cache_hit() -> None:
    venue = Venue(
        id=1,
        canonical_name="CVPR",
        venue_type=VenueType.CONFERENCE,
        rankings=[
            VenueRanking(
                ranking_system="core",
                level="A*",
                edition_year=2026,
            )
        ],
    )
    repository = FakeVenueRepository(venue=None)
    cache = FakeVenueCache({"CVPR": venue})
    service = VenueQualityService(repository, cache)
    requirement = VenueQualityRequirement(
        ranking_system="core",
        allowed_levels=["A*"],
    )

    matches = asyncio.run(service.matches_requirement("CVPR", requirement))

    assert matches is True
    assert cache.requested_names == ["CVPR"]
    assert repository.requested_names == []


def test_quality_service_populates_all_candidates_after_cache_miss() -> None:
    venue = Venue(
        id=2,
        canonical_name="AAAI Conference on Artificial Intelligence",
        venue_type=VenueType.CONFERENCE,
        rankings=[
            VenueRanking(
                ranking_system="core",
                level="A*",
                edition_year=2026,
            )
        ],
    )

    class CandidateVenueRepository:
        def __init__(self) -> None:
            self.requested_names: list[str] = []

        async def get_by_name(self, name: str) -> Venue | None:
            self.requested_names.append(name)
            if name == "AAAI Conference on Artificial Intelligence":
                return venue
            return None

    name = "Proceedings of the AAAI Conference on Artificial Intelligence"
    repository = CandidateVenueRepository()
    cache = FakeVenueCache()
    service = VenueQualityService(repository, cache)
    requirement = VenueQualityRequirement(
        ranking_system="core",
        allowed_levels=["A*"],
    )

    async def resolve_twice() -> tuple[bool, bool]:
        first = await service.matches_requirement(name, requirement)
        second = await service.matches_requirement(name, requirement)
        return first, second

    first, second = asyncio.run(resolve_twice())

    assert first is True
    assert second is True
    assert repository.requested_names == [
        name,
        "AAAI Conference on Artificial Intelligence",
    ]
    assert cache.stored_names == [
        name,
        "AAAI Conference on Artificial Intelligence",
    ]
