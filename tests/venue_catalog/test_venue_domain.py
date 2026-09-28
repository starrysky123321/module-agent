import pytest
from pydantic import ValidationError

from module_agent.venue_catalog.domain.models import Venue, VenueRanking, VenueType


def test_venue_uses_independent_empty_collections_by_default() -> None:
    first = Venue(
        canonical_name="CVPR",
        venue_type=VenueType.CONFERENCE,
    )
    second = Venue(
        canonical_name="JMLR",
        venue_type=VenueType.JOURNAL,
    )

    first.aliases.append("Computer Vision and Pattern Recognition")

    assert first.id is None
    assert first.rankings == []
    assert second.aliases == []
    assert second.rankings == []


def test_venue_contains_aliases_and_ranking_records() -> None:
    ranking = VenueRanking(
        ranking_system="ccf",
        level="A",
        edition_year=2022,
    )
    venue = Venue(
        id=1,
        canonical_name="CVPR",
        venue_type=VenueType.CONFERENCE,
        aliases=["IEEE/CVF Conference on Computer Vision and Pattern Recognition"],
        rankings=[ranking],
    )

    assert venue.venue_type is VenueType.CONFERENCE
    assert venue.rankings[0].level == "A"
    assert venue.rankings[0].category is None
    assert venue.rankings[0].source_url is None


@pytest.mark.parametrize(
    ("model", "values"),
    [
        (Venue, {"canonical_name": "", "venue_type": VenueType.CONFERENCE}),
        (
            VenueRanking,
            {"ranking_system": "", "level": "A", "edition_year": 2022},
        ),
        (
            VenueRanking,
            {"ranking_system": "ccf", "level": "", "edition_year": 2022},
        ),
    ],
)
def test_venue_models_reject_empty_required_strings(
    model: type[Venue] | type[VenueRanking],
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(values)
