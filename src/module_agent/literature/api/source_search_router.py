from typing import Annotated

from fastapi import APIRouter, Depends

from module_agent.bootstrap.api_dependencies import get_literature_search_service
from module_agent.literature.domain.search import SearchRequest, SearchResponse
from module_agent.literature.application.search import LiteratureSearchService


source_search_router = APIRouter(prefix="/search", tags=["literature"])


@source_search_router.post("/", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    service: Annotated[
        LiteratureSearchService,
        Depends(get_literature_search_service),
    ],
) -> SearchResponse:
    """搜索符合条件的结果。"""
    return await service.search(request)
