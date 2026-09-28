from time import perf_counter

from typesafe_sdk import AsyncTypeSafeClient, Choice

from module_agent.supervision.domain import (
    FailureDisposition,
    SupervisorFailureAdvice,
    WorkflowFailure,
)


QUESTION_NAME = "failure_disposition"


class JevFailureAdvisor:
    """封装 JevFailureAdvisor 相关的数据和行为。"""
    def __init__(
        self,
        client: AsyncTypeSafeClient,
    ) -> None:
        """初始化当前对象。"""
        self.client = client

    async def advise(
        self,
        failure: WorkflowFailure,
    ) -> SupervisorFailureAdvice:
        """为当前失败生成处置建议。"""
        started_at = perf_counter()

        response = await self.client.system_one(
            state={
                "step": failure.step.value,
                "category": failure.category.value,
                "message": failure.message,
                "attempt": failure.attempt,
                "error_type": failure.error_type,
            },
            questions={
                QUESTION_NAME: Choice(
                    instructions=(
                        "Should this workflow failure be retried "
                        "or should execution stop?"
                    ),
                    criteria={
                        FailureDisposition.RETRY.value: (
                            "The failure appears transient and repeating "
                            "the stage is likely to succeed safely."
                        ),
                        FailureDisposition.STOP.value: (
                            "The failure appears permanent, unsafe to "
                            "repeat, or lacks evidence that retry helps."
                        ),
                    },
                )
            },
        )

        answer = response.choices.get(QUESTION_NAME)
        if answer is None:
            raise RuntimeError(
                "Jev returned no failure disposition"
            )

        latency_ms = round(
            (perf_counter() - started_at) * 1000
        )


        return SupervisorFailureAdvice.model_validate(
            {
                "disposition": answer.choice,
                "confidence": answer.confidence,
                "probabilities": answer.probabilities,
                "model": response.model,
                "request_id": getattr(
                    response,
                    "request_id",
                    None,
                ),
                "latency_ms": latency_ms,
            }
        )
