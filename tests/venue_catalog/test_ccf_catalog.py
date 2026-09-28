from module_agent.venue_catalog.domain.models import VenueType
from module_agent.venue_catalog.adapters.database.importer import (
    _merge_records,
)
from module_agent.venue_catalog.adapters.rankings.ccf import (
    CCFVenueRecord,
    _extract_aliases,
)


def test_ccf_alias_parser_handles_wrapped_and_former_acronyms() -> None:
    aliases = _extract_aliases(
        "ACM SIGOPS ATC\n（原 USENIX ATC）",
        "ACM SIGOPS Annual Technical Conference",
    )

    assert aliases == ("ACM SIGOPS ATC", "USENIX ATC")


def test_ccf_import_merges_categories_for_the_same_venue() -> None:
    records = [
        CCFVenueRecord(
            canonical_name="Example Journal",
            aliases=("EJ",),
            venue_type=VenueType.JOURNAL,
            level="A",
            category="人工智能",
        ),
        CCFVenueRecord(
            canonical_name="Example Journal",
            aliases=("EJ",),
            venue_type=VenueType.JOURNAL,
            level="B",
            category="交叉/综合/新兴",
        ),
    ]

    merged = _merge_records(records)

    assert len(merged) == 1
    venue = next(iter(merged.values()))
    assert venue.aliases == {"ej": "EJ"}
    assert len(venue.rankings) == 2


def test_ccf_import_keeps_same_name_journal_and_conference_separate() -> None:
    records = [
        CCFVenueRecord(
            canonical_name="Computational Visual Media",
            aliases=("CVMJ",),
            venue_type=VenueType.JOURNAL,
            level="B",
            category="计算机图形学与多媒体",
        ),
        CCFVenueRecord(
            canonical_name="Computational Visual Media",
            aliases=("CVM",),
            venue_type=VenueType.CONFERENCE,
            level="C",
            category="计算机图形学与多媒体",
        ),
    ]

    merged = _merge_records(records)

    assert len(merged) == 2
