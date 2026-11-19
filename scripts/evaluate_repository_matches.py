"""Replay manually labelled repository candidates using the production scorer."""

import json
from pathlib import Path

from module_agent.code.application.scoring import RepositoryScoringService
from module_agent.code.domain.repository import (
    RepositoryCandidate,
    RepositoryEvidence,
    RepositoryEvidenceType,
    RepositoryOrigin,
)
from module_agent.code.domain.request import CodePaperInput

FIXTURES = Path(__file__).resolve().parents[1] / "eval" / "repository-matches.json"
THRESHOLD = 0.7  # Code Agent's default confidence gate.


def build_candidate(row: dict) -> RepositoryCandidate:
    full_name = row["full_name"]
    evidence = []
    if mention_url := row.get("mention_url"):
        evidence.append(RepositoryEvidence(
            evidence_type=RepositoryEvidenceType.PAPER_URL,
            description="Candidate appeared as a link in the paper or its publisher page",
            source_url=mention_url,
            weight=0.95,  # Old link weight, capped by the current scorer.
        ))
    return RepositoryCandidate(
        full_name=full_name, repository_url=f"https://github.com/{full_name}",
        owner_login=full_name.split("/", 1)[0], description=row["description"], evidence=evidence,
    )


def main() -> None:
    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
    scorer = RepositoryScoringService()
    results = []
    negative_pairs = false_attributions = incorrect_selections = 0
    for fixture in fixtures:
        paper = CodePaperInput.model_validate(fixture["paper"])
        labels = {row["full_name"]: row["label"] for row in fixture["candidates"]}
        candidates = scorer.score_many(paper, [build_candidate(row) for row in fixture["candidates"]])
        selected = candidates[0].full_name if candidates and candidates[0].confidence >= THRESHOLD else None
        expected = fixture["expected_repository"]
        incorrect_selections += selected != expected
        for candidate in candidates:
            if labels[candidate.full_name] != "official":
                negative_pairs += 1
                false_attributions += candidate.origin in {RepositoryOrigin.AUTHOR, RepositoryOrigin.OFFICIAL}
        results.append({
            "id": fixture["id"], "selected": selected, "expected": expected,
            "candidates": [
                {
                    "repository": candidate.full_name, "confidence": candidate.confidence,
                    "origin": candidate.origin, "label": labels[candidate.full_name],
                }
                for candidate in candidates
            ],
        })
    print(json.dumps({
        "confidence_threshold": THRESHOLD,
        "paper_cases": len(results),
        "incorrect_selections": incorrect_selections,
        "negative_candidate_pairs": negative_pairs,
        "incorrect_official_or_author_attributions": false_attributions,
        "cases": results,
    }, ensure_ascii=False, indent=2))
    if incorrect_selections or false_attributions:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
