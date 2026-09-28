from module_agent.shared.logging import logger
from module_agent.supervision.domain import (
    SupervisorFailureObservation,
)


class LoggingSupervisorObservationSink:
    """接收并保存观察数据。"""
    async def record(
        self,
        observation: SupervisorFailureObservation,
    ) -> None:
        """记录本次观察结果。"""
        logger.info(
            "supervisor_failure_shadow_observation | {}",
            observation.model_dump(mode="json"),
        )
