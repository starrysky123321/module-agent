import re
import unicodedata
from collections.abc import Sequence

from module_agent.code.domain.repository import (
    RepositoryCandidate,
    RepositoryEvidence,
    RepositoryEvidenceType,
    RepositoryOrigin,
)
from module_agent.code.domain.request import CodePaperInput


TITLE_WEIGHT = 0.35
DOI_WEIGHT = 0.55
AUTHOR_WEIGHT = 0.15
DIRECT_URL_WEIGHT = 0.95
MAX_KEYWORD_WEIGHT = 0.15
ARCHIVED_PENALTY = 0.8

STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "for",
        "from",
        "in",
        "of",
        "on",
        "the",
        "to",
        "with",
    }
)


class RepositoryScoringService:
    """使用确定性规则为仓库候选生成可解释评分。"""

    def score(
        self,
        paper: CodePaperInput,
        candidate: RepositoryCandidate,
    ) -> RepositoryCandidate:
        """计算一个候选仓库的证据、来源和置信度。"""
        evidence = list(candidate.evidence)
        raw_text = "\n".join(
            value
            for value in (
                candidate.full_name,
                candidate.description,
                " ".join(candidate.topics),
                candidate.readme_text,
            )
            if value
        )
        normalized_text = _normalize_text(raw_text)

        if _paper_links_repository(paper, candidate):
            evidence.append(
                RepositoryEvidence(
                    evidence_type=RepositoryEvidenceType.PAPER_URL,
                    description="Paper metadata links directly to this repository",
                    weight=DIRECT_URL_WEIGHT,
                    source_url=candidate.repository_url,
                )
            )

        normalized_doi = _normalize_doi(paper.doi)
        if normalized_doi and normalized_doi in raw_text.casefold():
            evidence.append(
                RepositoryEvidence(
                    evidence_type=RepositoryEvidenceType.DOI,
                    description="Repository metadata or README contains the paper DOI",
                    weight=DOI_WEIGHT,
                    source_url=candidate.repository_url,
                )
            )

        normalized_title = _normalize_text(paper.title)
        if normalized_title and normalized_title in normalized_text:
            evidence.append(
                RepositoryEvidence(
                    evidence_type=RepositoryEvidenceType.TITLE,
                    description="Repository metadata or README contains the paper title",
                    weight=TITLE_WEIGHT,
                    source_url=candidate.repository_url,
                )
            )

        if _owner_matches_author(candidate.owner_login, paper.authors):
            evidence.append(
                RepositoryEvidence(
                    evidence_type=RepositoryEvidenceType.AUTHOR,
                    description="Repository owner matches a paper author",
                    weight=AUTHOR_WEIGHT,
                    source_url=candidate.repository_url,
                )
            )

        keyword_coverage = _title_keyword_coverage(
            paper.title,
            normalized_text,
        )
        if keyword_coverage >= 0.4 and not _has_evidence(
            evidence,
            RepositoryEvidenceType.TITLE,
        ):
            evidence.append(
                RepositoryEvidence(
                    evidence_type=RepositoryEvidenceType.KEYWORD,
                    description=(
                        "Repository metadata matches "
                        f"{keyword_coverage:.0%} of significant title terms"
                    ),
                    weight=round(MAX_KEYWORD_WEIGHT * keyword_coverage, 4),
                    source_url=candidate.repository_url,
                )
            )

        evidence = _deduplicate_evidence(evidence)
        confidence = min(1.0, sum(item.weight for item in evidence))
        if candidate.archived:
            confidence *= ARCHIVED_PENALTY
        confidence = round(confidence, 4)

        return candidate.model_copy(
            update={
                "origin": _classify_origin(evidence),
                "confidence": confidence,
                "evidence": evidence,
            }
        )

    def score_many(
        self,
        paper: CodePaperInput,
        candidates: Sequence[RepositoryCandidate],
    ) -> list[RepositoryCandidate]:
        """评分全部候选，并按可信度从高到低排序。"""
        scored = [self.score(paper, candidate) for candidate in candidates]
        return sorted(
            scored,
            key=lambda candidate: (
                candidate.confidence,
                not candidate.archived,
                candidate.full_name.casefold(),
            ),
            reverse=True,
        )


def _normalize_text(value: str) -> str:
    """统一文本的 Unicode、大小写、标点和空白。"""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _normalize_doi(value: str | None) -> str | None:
    """去掉 DOI URL 前缀并转成小写。"""
    if not value:
        return None
    normalized = value.strip().casefold()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
    ):
        if normalized.startswith(prefix):
            return normalized[len(prefix) :]
    return normalized


def _paper_links_repository(
    paper: CodePaperInput,
    candidate: RepositoryCandidate,
) -> bool:
    """判断论文元数据是否直接指向候选仓库。"""
    if not paper.landing_page_url:
        return False
    paper_url = paper.landing_page_url.rstrip("/").casefold()
    repository_url = str(candidate.repository_url).rstrip("/").casefold()
    return paper_url == repository_url or repository_url in paper_url


def _owner_matches_author(owner_login: str, authors: Sequence[str]) -> bool:
    """判断仓库账号是否与任一论文作者匹配。"""
    normalized_owner = _normalize_identifier(owner_login)
    if not normalized_owner:
        return False

    for author in authors:
        normalized_author = _normalize_identifier(author)
        author_parts = _normalize_text(author).split()
        surname = _normalize_identifier(author_parts[-1]) if author_parts else ""
        if normalized_owner == normalized_author:
            return True
        if len(surname) >= 4 and surname in normalized_owner:
            return True
    return False


def _normalize_identifier(value: str) -> str:
    """移除标识中的非字母数字字符。"""
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _title_keyword_coverage(title: str, normalized_text: str) -> float:
    """计算仓库文本覆盖论文有效标题词的比例。"""
    title_terms = {
        term
        for term in _normalize_text(title).split()
        if len(term) >= 3 and term not in STOP_WORDS
    }
    if not title_terms:
        return 0.0
    repository_terms = set(normalized_text.split())
    return len(title_terms & repository_terms) / len(title_terms)


def _has_evidence(
    evidence: Sequence[RepositoryEvidence],
    evidence_type: RepositoryEvidenceType,
) -> bool:
    """判断证据列表是否已经包含指定类型。"""
    return any(item.evidence_type is evidence_type for item in evidence)


def _deduplicate_evidence(
    evidence: Sequence[RepositoryEvidence],
) -> list[RepositoryEvidence]:
    """根据类型和描述去除重复证据。"""
    result: list[RepositoryEvidence] = []
    seen: set[tuple[RepositoryEvidenceType, str]] = set()
    for item in evidence:
        key = (item.evidence_type, item.description)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _classify_origin(
    evidence: Sequence[RepositoryEvidence],
) -> RepositoryOrigin:
    """根据证据组合判断仓库归属。"""
    evidence_types = {item.evidence_type for item in evidence}
    if RepositoryEvidenceType.PAPER_URL in evidence_types:
        return RepositoryOrigin.OFFICIAL
    if (
        RepositoryEvidenceType.AUTHOR in evidence_types
        and evidence_types
        & {RepositoryEvidenceType.DOI, RepositoryEvidenceType.TITLE}
    ):
        return RepositoryOrigin.AUTHOR
    return RepositoryOrigin.UNKNOWN
