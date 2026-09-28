import json
from collections.abc import Sequence

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from module_agent.literature.domain.search import PaperSearchResult, SearchRequest
from module_agent.literature.domain.method import (
    PaperMethodExtractionResult,
    PaperMethodProfile,
)
from module_agent.shared.llm.usage import (
    capture_completion_usage,
    clear_llm_token_usage,
)


MAX_QWEN_PROFILE_PAPERS = 10


class QwenMethodResponse(BaseModel):
    """The model can report paper claims, not runtime measurements."""

    # 论文方法画像列表。
    profiles: list[PaperMethodProfile] = Field(default_factory=list)
    # 不阻断流程的警告列表。
    warnings: list[str] = Field(default_factory=list)

SYSTEM_PROMPT = """
You extract computer science methods from paper titles and abstracts.

For each input paper, return exactly one PaperMethodProfile. Preserve its
source and source_id exactly. Use the user's request only to understand which
aspects of the method matter; do not use it as evidence about the paper.

Rules:
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
            raise ValueError("Qwen returned no parsed method extraction result")

        domain_result = PaperMethodExtractionResult(profiles=result.profiles)
        self._validate_result(papers, domain_result)
        return domain_result

    @staticmethod
    def _validate_result(
        papers: Sequence[PaperSearchResult],
        result: PaperMethodExtractionResult,
    ) -> None:
        papers_by_identity = {
            (paper.source, paper.source_id): paper for paper in papers
        }
        actual_ids = [
            (profile.source, profile.source_id) for profile in result.profiles
        ]
        if (
            len(actual_ids) != len(papers_by_identity)
            or len(set(actual_ids)) != len(actual_ids)
            or set(actual_ids) != set(papers_by_identity)
        ):
            raise ValueError("Qwen method profiles do not match input papers")

        for profile in result.profiles:
            paper = papers_by_identity[(profile.source, profile.source_id)]
            QwenPaperMethodExtractor._validate_evidence(paper, profile)

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
            raise ValueError(
                "Qwen method profile has claims without paper evidence"
            )

        for evidence in profile.evidence:
            source_text = (
                paper.title
                if evidence.field == "title"
                else paper.abstract or ""
            )
            excerpt = evidence.excerpt.strip()
            if not excerpt or excerpt.casefold() not in source_text.casefold():
                raise ValueError(
                    "Qwen method profile evidence is not in the paper metadata"
                )
