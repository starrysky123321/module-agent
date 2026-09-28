import asyncio
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from module_agent.venue_catalog.domain.models import VenueType
from module_agent.venue_catalog.adapters.database.models import (
    VenueAliasModel,
    VenueModel,
    VenueRankingModel,
)
from module_agent.venue_catalog.adapters.database.repository import (
    SqlAlchemyVenueRepository,
)


def test_venue_repository_maps_orm_model_to_domain_entity() -> None:
    venue_model = VenueModel(
        id=1,
        canonical_name="CVPR",
        normalized_name="cvpr",
        venue_type=VenueType.CONFERENCE,
        aliases=[
            VenueAliasModel(
                alias="Computer Vision and Pattern Recognition",
                normalized_alias="computer vision and pattern recognition",
            )
        ],
        rankings=[
            VenueRankingModel(
                ranking_system="ccf",
                level="A",
                edition_year=2022,
            )
        ],
    )
    result = MagicMock()
    result.scalars.return_value.unique.return_value.all.return_value = [venue_model]
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result
    repository = SqlAlchemyVenueRepository(session)

    venue = asyncio.run(repository.get_by_name("  CvPr "))

    assert venue is not None
    assert venue.id == 1
    assert venue.canonical_name == "CVPR"
    assert venue.aliases == ["Computer Vision and Pattern Recognition"]
    assert venue.rankings[0].ranking_system == "ccf"
    assert venue.rankings[0].level == "A"

    statement = session.execute.await_args.args[0]
    assert "cvpr" in statement.compile().params.values()


def test_venue_repository_returns_none_when_name_is_unknown() -> None:
    result = MagicMock()
    result.scalars.return_value.unique.return_value.all.return_value = []
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result
    repository = SqlAlchemyVenueRepository(session)

    venue = asyncio.run(repository.get_by_name("unknown"))

    assert venue is None


def test_venue_repository_returns_none_for_ambiguous_alias() -> None:
    venue_models = [
        VenueModel(
            id=1,
            canonical_name="Transactions on Cloud Computing",
            normalized_name="transactions on cloud computing",
            venue_type=VenueType.JOURNAL,
        ),
        VenueModel(
            id=2,
            canonical_name="Theory of Cryptography Conference",
            normalized_name="theory of cryptography conference",
            venue_type=VenueType.CONFERENCE,
        ),
    ]
    result = MagicMock()
    result.scalars.return_value.unique.return_value.all.return_value = venue_models
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result
    repository = SqlAlchemyVenueRepository(session)

    venue = asyncio.run(repository.get_by_name("TCC"))

    assert venue is None


def test_venue_repository_prefers_canonical_name_over_colliding_alias() -> None:
    canonical_venue = VenueModel(
        id=1,
        canonical_name="Example Venue",
        normalized_name="example venue",
        venue_type=VenueType.CONFERENCE,
    )
    alias_collision = VenueModel(
        id=2,
        canonical_name="Other Venue",
        normalized_name="other venue",
        venue_type=VenueType.CONFERENCE,
    )
    result = MagicMock()
    result.scalars.return_value.unique.return_value.all.return_value = [
        canonical_venue,
        alias_collision,
    ]
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result
    repository = SqlAlchemyVenueRepository(session)

    venue = asyncio.run(repository.get_by_name(" Example Venue "))

    assert venue is not None
    assert venue.id == 1
