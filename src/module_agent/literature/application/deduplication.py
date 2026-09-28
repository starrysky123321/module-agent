from collections.abc import Sequence

from module_agent.literature.domain.search import PaperSearchResult
from module_agent.literature.domain.normalization import (
    normalize_doi,
    normalize_title,
)


PREPRINT_MARKERS = frozenset(
    {
        "preprint",
        "posted-content",
        "posted content",
    }
)


def paper_preference_key(
    paper: PaperSearchResult,
) -> tuple[int, int, int, int, int]:
    """Return a key whose larger value represents a preferred record."""

    publication_type = (paper.publication_type or "").strip().casefold()

    if publication_type in PREPRINT_MARKERS:
        publication_rank = 0
    elif publication_type:
        publication_rank = 2
    else:
        publication_rank = 1

    return (
        publication_rank,
        int(bool(paper.venue)),
        int(bool(paper.doi)),
        int(bool(paper.abstract)),
        paper.cited_by_count,
    )


def deduplicate_papers(
    papers: Sequence[PaperSearchResult],
) -> list[PaperSearchResult]:
    """Group papers by DOI or normalized title and retain the best record."""

    if not papers:
        return []

    parents = list(range(len(papers)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return

        # Keep the earliest record as the group root so group ordering is stable.
        if left_root < right_root:
            parents[right_root] = left_root
        else:
            parents[left_root] = right_root

    key_owner: dict[tuple[str, str], int] = {}

    for index, paper in enumerate(papers):
        normalized_doi = normalize_doi(paper.doi)
        normalized_title = normalize_title(paper.title)
        keys: list[tuple[str, str]] = []

        if normalized_doi:
            keys.append(("doi", normalized_doi.casefold()))
        if normalized_title:
            keys.append(("title", normalized_title))

        for key in keys:
            owner = key_owner.get(key)
            if owner is None:
                key_owner[key] = index
            else:
                union(index, owner)

    groups: dict[int, list[PaperSearchResult]] = {}
    for index, paper in enumerate(papers):
        groups.setdefault(find(index), []).append(paper)

    return [
        max(group, key=paper_preference_key)
        for _, group in sorted(groups.items())
    ]
