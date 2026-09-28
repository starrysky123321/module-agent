from module_agent.literature.adapters.sources.openalex import (
    normalize_doi,
    parse_work,
    rebuild_abstract,
)
from module_agent.literature.domain.normalization import normalize_title


def test_rebuild_abstract() -> None:
    inverted_index = {
        "Small": [0],
        "object": [1],
        "detection": [2],
    }

    assert rebuild_abstract(inverted_index) == "Small object detection"


def test_normalize_doi() -> None:
    assert normalize_doi("https://doi.org/10.1000/example") == "10.1000/example"
    assert normalize_doi(None) is None


def test_normalize_title_normalizes_unicode_case_and_punctuation() -> None:
    assert normalize_title(
        "  ＳＥＭＡ-YOLO: Lightweight Small_Object Detection!  "
    ) == "sema yolo lightweight small object detection"


def test_parse_work() -> None:
    work = {
        "id": "https://openalex.org/W123",
        "doi": "https://doi.org/10.1000/example",
        "title": "Example Paper",
        "publication_year": 2025,
        "publication_date": "2025-01-01",
        "type": "article",
        "authorships": [
            {"author": {"display_name": "Alice"}},
            {"author": {"display_name": "Bob"}},
        ],
        "primary_location": {
            "source": {"display_name": "Example Conference"},
            "landing_page_url": "https://example.com/paper",
            "pdf_url": None,
        },
        "best_oa_location": {
            "landing_page_url": "https://example.com/open-paper",
            "pdf_url": "https://example.com/paper.pdf",
        },
        "open_access": {"is_oa": True, "oa_status": "green"},
        "abstract_inverted_index": {"Example": [0], "abstract": [1]},
        "cited_by_count": 12,
    }

    paper = parse_work(work)

    assert paper.source_id == "https://openalex.org/W123"
    assert paper.title == "Example Paper"
    assert paper.authors == ["Alice", "Bob"]
    assert paper.venue == "Example Conference"
    assert paper.doi == "10.1000/example"
    assert paper.abstract == "Example abstract"
    assert paper.pdf_url == "https://example.com/paper.pdf"
    assert paper.is_open_access is True
