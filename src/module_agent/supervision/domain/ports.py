from typing import Protocol

from module_agent.supervision.domain.decision import (
    SupervisorDecision,
)
from module_agent.workflow.domain import (
    ModuleGraphState,
    WorkflowStatus,
)
from module_agent.supervision.domain.advice import (
    SupervisorFailureAdvice,
    SupervisorFailureObservation,
)
from module_agent.supervision.domain.failure import WorkflowFailure
from module_agent.supervision.domain.statistics import (
    SupervisorFailureObservationRecord,
    SupervisorObservationStats,
)
from module_agent.supervision.domain.observation_query import (
    SupervisorObservationListQuery,
)
from datetime import datetime


class SupervisorDecisionPolicy(Protocol):
    """定义业务决策策略。"""
    async def decide(
        self,
        state: ModuleGraphState,
        status: WorkflowStatus,
    ) -> SupervisorDecision:
        """根据当前状态生成决策。"""
        ...

class SupervisorFailureAdvisor(Protocol):
    """封装 SupervisorFailureAdvisor 相关的数据和行为。"""
    async def advise(
        self,
        failure: WorkflowFailure,
    ) -> SupervisorFailureAdvice:
        """为当前失败生成处置建议。"""
        ...


class SupervisorObservationSink(Protocol):
    """接收并保存观察数据。"""
    async def record(
        self,
        observation: SupervisorFailureObservation,
    ) -> None:
        """记录本次观察结果。"""
        ...


class SupervisorObservationStatsReader(Protocol):
    """封装 SupervisorObservationStatsReader 相关的数据和行为。"""
    async def get_stats(
        self,
        literature_run_id: int | None = None,
        *,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> SupervisorObservationStats:
        """获取对应记录。"""
        ...

    async def list_observations(
        self,
        query: SupervisorObservationListQuery,
    ) -> list[SupervisorFailureObservationRecord]:
        """列出符合条件的记录。"""
        ...
