import json
import time

from openai import AsyncOpenAI

from module_agent.code.domain.artifact import ReproductionPlan
from module_agent.code.domain.request import CodePaperInput
from module_agent.shared.llm.usage import (
    capture_completion_usage,
    clear_llm_token_usage,
)
from module_agent.shared.metrics import observe_llm_call

SYSTEM_PROMPT = """
You create implementation plans for computer science
papers when no trusted
source-code repository is available.

Rules:
- Use only the supplied paper metadata and method
profile.
- Return a concrete implementation plan, not completed
source code.
- Do not claim that code has been implemented, executed,
or verified.
- Clearly record missing information and uncertainties
in open_questions
or warnings.
- Treat the user's code requirements as constraints, not
as facts stated
by the paper.
""".strip()


class QwenReproductionPlanner:
    """封装 QwenReproductionPlanner 相关的数据和行为。"""
    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        """初始化当前对象。"""
        normalized_model = model.strip()
        if not normalized_model:
            raise ValueError("model 不能为空")

        self.client = client
        self.model = normalized_model


    async def plan(
        self,
        paper: CodePaperInput,
        *,
        code_requirements: str | None = None,
    ) -> ReproductionPlan:
        """生成当前阶段的结构化计划。"""
        payload = {
            "paper": paper.model_dump(mode="json"),
            "code_requirements": code_requirements,
        }
        
        started_at = time.perf_counter()
        clear_llm_token_usage()
        try:
            completion = await self.client.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
                response_format=ReproductionPlan,
            )
            usage = capture_completion_usage(completion)
        except Exception:
            observe_llm_call(
                stage="reproduction_planning",
                model=self.model,
                outcome="failed",
                duration_seconds=time.perf_counter() - started_at,
            )
            raise
        observe_llm_call(
            stage="reproduction_planning",
            model=self.model,
            outcome="success",
            duration_seconds=time.perf_counter() - started_at,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
        )
        
        result = completion.choices[0].message.parsed
        
        
        if result is None:
            raise ValueError("Qwen returned no parsed reproduction plan")

        return result
        
        
