import json
from collections.abc import Mapping, Sequence

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, SkipValidation, ValidationError

from module_agent.literature.domain.search import PaperSearchResult, SearchRequest
from module_agent.literature.domain.method import (
    PaperMethodExtractionResult,
    PaperMethodProfile,
    PaperMethodExtractionError,
    PaperMethodExtractionIssue,
)
from module_agent.shared.logging import logger
from module_agent.shared.llm.usage import (
    capture_completion_usage,
    clear_llm_token_usage,
)


MAX_QWEN_PROFILE_PAPERS = 10


class QwenMethodResponse(BaseModel):
    """The model can report paper claims, not runtime measurements."""

    # 论文方法画像列表。
    # Keep the provider's full schema, but validate each returned item separately.
    profiles: list[SkipValidation[PaperMethodProfile]] = Field(default_factory=list)
    # 不阻断流程的警告列表。
    warnings: list[str] = Field(default_factory=list)

SYSTEM_PROMPT = """
You extract computer science methods from paper titles and abstracts.

For each input paper, return exactly one PaperMethodProfile. Preserve its
source and source_id exactly. Use the user's request only to understand which
aspects of the method matter; do not use it as evidence about the paper.

Rules:
- Write descriptive fields (research_problem, module_type, core_method, inputs,
  outputs and explanation text) in Simplified Chinese. Keep source identifiers,
  code identifiers and evidence excerpts exactly as supplied, without translation.
- Base every claim solely on that paper's supplied title and abstract.
- Use null or an empty list when the metadata does not establish a field.
- Do not infer algorithms, modules, inputs, outputs, or tasks that are not stated.
- Every evidence excerpt must be an exact, contiguous substring of the
  corresponding title or abstract, and its field must identify that source.
- If you extract any substantive information, provide at least one excerpt.
- Do not infer whether the paper's code is open source. Paper open access and
  code open source are separate facts.
- Set confidence according to how explicitly the supplied text supports the
  extracted information. Return an empty warnings list.
""".strip()


class QwenPaperMethodExtractor:
    """封装 QwenPaperMethodExtractor 相关的数据和行为。"""
    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        """初始化当前对象。"""
        normalized_model = model.strip()
        if not normalized_model:
            raise ValueError("model 不能为空")

        self.client = client
        self.model = normalized_model

    async def extract_many(
        self,
        request: SearchRequest,
        papers: Sequence[PaperSearchResult],
    ) -> PaperMethodExtractionResult:
        """批量提取结构化信息。"""
        if not papers:
            return PaperMethodExtractionResult()

        if len(papers) > MAX_QWEN_PROFILE_PAPERS:
            raise ValueError(
                "Qwen method extractor accepts at most "
                f"{MAX_QWEN_PROFILE_PAPERS} papers"
            )

        identities = [(paper.source, paper.source_id) for paper in papers]
        if len(set(identities)) != len(identities):
            raise ValueError("Input papers contain duplicate identities")

        payload = {
            "request": {
                "topic": request.topic,
                "description": request.description,
                "keywords": request.keywords,
            },
            "papers": [
                {
                    "source": paper.source,
                    "source_id": paper.source_id,
                    "title": paper.title,
                    "abstract": paper.abstract,
                }
                for paper in papers
            ],
        }

        clear_llm_token_usage()
        completion = await self.client.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            response_format=QwenMethodResponse,
        )
        capture_completion_usage(completion)

        result = completion.choices[0].message.parsed
        if result is None:
            raise PaperMethodExtractionError(
                "no_parsed_result", "Qwen returned no parsed method extraction result"
            )

        return self._validate_result(papers, result.profiles)

    @staticmethod
    def _validate_result(
        papers: Sequence[PaperSearchResult],
        raw_profiles: Sequence[object],
    ) -> PaperMethodExtractionResult:
        """Keep grounded items and downgrade only their malformed/missing peers."""
        expected = {(paper.source, paper.source_id) for paper in papers}
        grouped: dict[tuple[str, str], list[object]] = {}
        profiles: list[PaperMethodProfile] = []
        issues: list[PaperMethodExtractionIssue] = []

        for index, raw in enumerate(raw_profiles):
            data = raw.model_dump(mode="python") if isinstance(raw, PaperMethodProfile) else raw
            source = data.get("source") if isinstance(data, Mapping) else None
            source_id = data.get("source_id") if isinstance(data, Mapping) else None
            identity = (source, source_id) if isinstance(source, str) and isinstance(source_id, str) else None
            if identity is None or identity not in expected:
                issues.append(PaperMethodExtractionIssue(
                    # Untrusted unmatched output is identified by position, not echoed.
                    code="unexpected_profile",
                    message=f"Returned profile at index {index} has no matching input paper identity",
                    fallback=False,
                ))
                continue
            grouped.setdefault(identity, []).append(data)

        for paper in papers:
            matches = grouped.get((paper.source, paper.source_id), [])
            try:
                if not matches:
                    raise PaperMethodExtractionError("missing_profile", "Qwen did not return a profile for this input paper")
                if len(matches) != 1:
                    raise PaperMethodExtractionError("duplicate_profile", "Qwen returned multiple profiles for this input paper")
                try:
                    profile = PaperMethodProfile.model_validate(matches[0])
                except ValidationError as exc:
                    details = "; ".join(
                        f'{".".join(str(part) for part in error["loc"])}: {error["type"]}'
                        for error in exc.errors(include_input=False, include_context=False, include_url=False)[:3]
                    )
                    raise PaperMethodExtractionError("invalid_profile_schema", f"Profile fields failed validation ({details})") from exc
                QwenPaperMethodExtractor._validate_evidence(paper, profile)
            except PaperMethodExtractionError as exc:
                issues.append(PaperMethodExtractionIssue(
                    source=paper.source, source_id=paper.source_id,
                    code=exc.code, message=str(exc), evidence_field=exc.evidence_field,
                ))
                profile = PaperMethodProfile(source=paper.source, source_id=paper.source_id, confidence=0.0)
            profiles.append(profile)

        for issue in issues:
            logger.warning(
                "method extraction issue | source={!r} source_id={!r} code={} evidence_field={} reason={} fallback={}",
                issue.source, issue.source_id, issue.code, issue.evidence_field, issue.message, issue.fallback,
            )
        return PaperMethodExtractionResult(
            profiles=profiles, issues=issues,
            warnings=[issue.as_warning() for issue in issues],
        )

    @staticmethod
    def _validate_evidence(
        paper: PaperSearchResult,
        profile: PaperMethodProfile,
    ) -> None:
        has_claims = any(
            (
                profile.research_problem,
                profile.module_type,
                profile.core_method,
                profile.inputs,
                profile.outputs,
                profile.applicable_tasks,
            )
        )
        if has_claims and not profile.evidence:
            raise PaperMethodExtractionError(
                "claims_without_evidence", "Qwen method profile has claims without paper evidence"
            )

        for index, evidence in enumerate(profile.evidence):
            source_text = (
                paper.title
                if evidence.field == "title"
                else paper.abstract or ""
            )
            excerpt = evidence.excerpt.strip()
            if not excerpt or excerpt.casefold() not in source_text.casefold():
                raise PaperMethodExtractionError(
                    "evidence_not_in_metadata",
                    f"Evidence excerpt {index} is not in the paper metadata field {evidence.field}",
                    evidence_field=evidence.field,
                )
