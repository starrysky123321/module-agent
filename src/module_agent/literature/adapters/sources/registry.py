from module_agent.literature.domain.source import LiteratureSource
from module_agent.literature.adapters.sources.openalex import search_openalex
from module_agent.literature.adapters.sources.semantic_scholar import search_semantic_scholar


LITERATURE_SOURCE_REGISTRY = {
    "openalex": search_openalex,
    "semantic_scholar": search_semantic_scholar,
}