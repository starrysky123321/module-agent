import pytest
from module_agent.code.domain.request import CodePaperInput
from module_agent.literature.domain.search import PaperSearchResult


@pytest.mark.parametrize("model", [CodePaperInput, PaperSearchResult])
@pytest.mark.parametrize("value", [None, "", " \n "])
def test_missing_optional_urls_do_not_trigger_downloads(model, value):
    paper = model.model_validate(
        {
            "paper_id": 1,
            "source": "fixture",
            "source_id": "1",
            "title": "Fixture",
            "pdf_url": value,
            "landing_page_url": value,
        }
    )
    assert paper.pdf_url is None and paper.landing_page_url is None
