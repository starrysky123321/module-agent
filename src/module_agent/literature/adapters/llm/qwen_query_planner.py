from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from module_agent.literature.domain.search import SearchRequest
from module_agent.literature.domain.query import LiteratureQueryPlan
from module_agent.literature.domain.query import MAX_SEARCH_QUERIES
from module_agent.literature.domain.query import SearchQuery
from module_agent.shared.llm.usage import (
    capture_completion_usage,
    clear_llm_token_usage,
)


class QwenQueryPlanResponse(BaseModel):
    """Only fields the model is allowed to generate."""

    # 本次实际使用的检索词。
    search_queries: list[SearchQuery] = Field(
        min_length=1, max_length=MAX_SEARCH_QUERIES
    )
    # 不阻断流程的警告列表。
    warnings: list[str] = Field(default_factory=list)



SYSTEM_PROMPT =f"""
You are a computer science literature search query planner.

Generate 3 to {MAX_SEARCH_QUERIES} concise English search queries based on the
user's research request.

Requirements:
- Cover useful synonyms, abbreviations, full names, and related
  technical terms.
- Preserve the user's original research direction.
- Do not expand the queries into unrelated topics.
- Do not include date ranges or conference ranking requirements
  in the search queries. These will be filtered by later code.
- Return an empty warnings list.
""".strip()


class QwenLiteratureQueryPlanner:
    """封装 QwenLiteratureQueryPlanner 相关的数据和行为。"""
    def __init__(self, client: AsyncOpenAI, model: str):
        """初始化当前对象。"""
        self.client = client
        normalized_model = model.strip()
        if not normalized_model:
            raise ValueError("model 不能为空")
        self.model = normalized_model
        
    async def plan(self, request: SearchRequest) -> LiteratureQueryPlan:
        """生成当前阶段的结构化计划。"""
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
                    "content": request.model_dump_json(),
                },
            ],
            response_format=QwenQueryPlanResponse,
        )
        capture_completion_usage(completion)

        plan = completion.choices[0].message.parsed

        if plan is None:
            raise ValueError(
                "Qwen returned no parsed query plan"
            )

        return LiteratureQueryPlan(
            search_queries=plan.search_queries,
            warnings=plan.warnings,
        )
