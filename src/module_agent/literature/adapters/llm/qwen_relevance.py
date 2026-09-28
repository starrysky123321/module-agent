import json
from collections.abc import Sequence

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from module_agent.literature.domain.search import (
    PaperSearchResult,
    SearchRequest,
)
from module_agent.literature.domain.ranking import (
    PaperRelevanceAssessment,
    PaperRelevanceResult,
)
from module_agent.shared.llm.usage import (
    capture_completion_usage,
    clear_llm_token_usage,
)


class QwenRelevanceResponse(BaseModel):
    """The model cannot author runtime call metrics."""

    # 论文相关性评估列表。
    assessments: list[PaperRelevanceAssessment] = Field(default_factory=list)
    # 不阻断流程的警告列表。
    warnings: list[str] = Field(default_factory=list)

MAX_QWEN_RELEVANCE_PAPERS = 20

SYSTEM_PROMPT = """
  You are a computer science literature relevance
  evaluator.

  Evaluate whether each candidate paper directly addresses
  the user's
  research problem.

  Scoring guide:
  - 0.0: unrelated
  - 0.25: only shares a broad research field
  - 0.5: partially relevant
  - 0.75: directly relevant
  - 1.0: the user's problem is a central focus of the paper

  Requirements:
  - Judge only from the provided title and abstract.
  - Do not treat generic terms as strong evidence.
  - Do not invent information missing from the paper
  metadata.
  - Respect the requested contribution type. If the user asks
  for an algorithm, method, or reusable module, a pure survey or
  review that proposes no such method must score at most 0.5.
  Do not apply this cap when the user explicitly asks for surveys
  or reviews.
  - Return exactly one assessment for every provided paper.
  - Preserve each paper's source and source_id exactly.
  - Give a short, concrete reason for each score.
  - Return an empty warnings list.
  """.strip()


class QwenPaperRelevanceScorer:
    """封装 QwenPaperRelevanceScorer 相关的数据和行为。"""
    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        """初始化当前对象。"""
        normalized_model = model.strip()
        if not normalized_model:
            raise ValueError("model 不能为空")

        self.client = client
        self.model = normalized_model

    async def score_many(
        self,
        request: SearchRequest,
        search_queries: Sequence[str],
        papers: Sequence[PaperSearchResult],
    ) -> PaperRelevanceResult:
        """评分全部输入并按可信度排序。"""
        if not papers:
            return PaperRelevanceResult()

        if len(papers) > MAX_QWEN_RELEVANCE_PAPERS:
            raise ValueError(
                f"Qwen relevance scorer accepts at most "
                f"{MAX_QWEN_RELEVANCE_PAPERS} papers"
            )

        payload = {
            "request": {
                "topic": request.topic,
                "description": request.description,
                "keywords": request.keywords,
            },
            "search_queries": list(search_queries),
            "papers": [
                {
                    "source": paper.source,
                    "source_id": paper.source_id,
                    "title": paper.title,
                    "publication_type": paper.publication_type,
                    "abstract": paper.abstract,
                }
                for paper in papers
            ],
        }

        clear_llm_token_usage()
        completion = await self.client.chat.completions.parse(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        payload,
                        ensure_ascii=False,
                    ),
                },
            ],
            response_format=QwenRelevanceResponse,
        )
        capture_completion_usage(completion)

        result = completion.choices[0].message.parsed

        if result is None:
            raise ValueError(
                "Qwen returned no parsed relevance result"
            )

        domain_result = PaperRelevanceResult(assessments=result.assessments)
        self._validate_result(domain_result, papers)

        return domain_result

    @staticmethod
    def _validate_result(
        result: PaperRelevanceResult,
        papers: Sequence[PaperSearchResult],
    ) -> None:
        expected_ids = [
            (paper.source, paper.source_id)
            for paper in papers
        ]
        actual_ids = [
            (assessment.source, assessment.source_id)
            for assessment in result.assessments
        ]

        if len(set(expected_ids)) != len(expected_ids):
            raise ValueError(
                "Input papers contain duplicate identities"
            )

        if (
            len(actual_ids) != len(expected_ids)
            or set(actual_ids) != set(expected_ids)
        ):
            raise ValueError(
                "Qwen relevance result does not match input papers"
            )
