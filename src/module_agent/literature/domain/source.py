from collections.abc import Awaitable, Callable

from module_agent.literature.domain.search import PaperSearchResult, SearchRequest


LiteratureSource = Callable[
    [SearchRequest],
    Awaitable[list[PaperSearchResult]],
]
