from module_agent.venue_catalog.domain.models import VenueType
from module_agent.venue_catalog.adapters.database.models import (
    VenueModel,
    VenueRankingModel,
)
from module_agent.venue_catalog.adapters.database.importer import (
    _can_attach_rankings,
    _merge_records,
)
from module_agent.venue_catalog.adapters.rankings.icore import (
    ICOREVenueRecord,
    parse_icore_page,
)


def test_parse_icore_page_reads_official_table_fields() -> None:
    html = """
    <table>
      <tr>
        <th>Title</th><th>Acronym</th><th>Source</th><th>Rank</th>
        <th>Note</th><th>DBLP</th><th>Primary FoR</th><th>Comments</th>
        <th>Average Rating</th>
      </tr>
      <tr onclick="navigate('/conf-ranks/1234/')">
        <td>Example Conference</td><td>EC</td><td>ICORE2026</td><td>A*</td>
        <td>none</td><td>view</td><td>4606</td><td>2</td><td>4.5</td>
      </tr>
    </table>
    """

    records = parse_icore_page(html)

    assert records == [
        ICOREVenueRecord(
            canonical_name="Example Conference",
            aliases=("EC",),
            venue_type=VenueType.CONFERENCE,
            level="A*",
            category="4606",
            source_url="https://portal.core.edu.au/conf-ranks/1234/",
        )
    ]


def test_icore_merge_keeps_duplicate_acronyms_as_separate_venues() -> None:
    records = [
        ICOREVenueRecord(
            canonical_name="First Security Conference",
            aliases=("FSC",),
            venue_type=VenueType.CONFERENCE,
            level="A",
            category="4604",
        ),
        ICOREVenueRecord(
            canonical_name="Fast Systems Conference",
            aliases=("FSC",),
            venue_type=VenueType.CONFERENCE,
            level="B",
            category="4606",
        ),
    ]

    merged = _merge_records(records, ranking_system="core")

    assert len(merged) == 2
    assert all(venue.aliases == {"fsc": "FSC"} for venue in merged.values())


def test_icore_alias_merge_does_not_overwrite_a_different_source_record() -> None:
    venue = VenueModel(
        canonical_name="Existing Conference",
        normalized_name="existing conference",
        venue_type=VenueType.CONFERENCE,
        rankings=[
            VenueRankingModel(
                ranking_system="core",
                level="National: Korea",
                edition_year=2026,
                category="4604",
                source_url="https://portal.core.edu.au/conf-ranks/1077/",
            )
        ],
    )
    incoming = ICOREVenueRecord(
        canonical_name="Different Conference",
        aliases=("DC",),
        venue_type=VenueType.CONFERENCE,
        level="National: China",
        category="4604",
        source_url="https://portal.core.edu.au/conf-ranks/1736/",
    )

    can_attach = _can_attach_rankings(
        venue,
        {("core", 2026, "4604"): incoming},
    )

    assert can_attach is False
