from datetime import date

from module_agent.literature.domain.search import (
    SearchRequest,
    VenueQualityRequirement,
)


def test_search_request_accepts_quality_requirement_without_specific_venues() -> None:
    request = SearchRequest(
        topic="object detection",
        description="搜索高质量目标检测论文",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=[],
        exclusion_keywords=[],
        max_results=10,
        venue_quality=VenueQualityRequirement(
            ranking_system="ccf",
            allowed_levels=["A"],
        ),
    )

    assert request.venues == []
    assert request.venue_quality is not None
    assert request.venue_quality.ranking_system == "ccf"
    assert request.venue_quality.allowed_levels == ["A"]
