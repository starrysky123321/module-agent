"""RabbitMQ publisher for Code Agent jobs."""

from uuid import UUID, uuid4

from aio_pika import DeliveryMode, Message

from module_agent.code.adapters.messaging.topology import (
    declare_code_job_topology,
)
from module_agent.code.domain.jobs import CodeJob, ComputeTarget
from module_agent.code.domain.request import CodeAgentRequest
from module_agent.shared.messaging.rabbitmq import RabbitMQConnectionManager


class RabbitMQCodeJobQueue:
    """Routes durable jobs to CPU or GPU worker pools."""

    def __init__(self, connection_manager: RabbitMQConnectionManager) -> None:
        self.connection_manager = connection_manager

    async def enqueue(
        self,
        request: CodeAgentRequest,
        *,
        attempt: int,
        trace_id: UUID,
        compute_target: ComputeTarget = ComputeTarget.CPU,
    ) -> str:
        """Publish one validated job to its resource queue."""
        job = CodeJob(
            request=request,
            attempt=attempt,
            trace_id=trace_id,
            compute_target=compute_target,
        )
        message_id = uuid4().hex
        connection = await self.connection_manager.get_connection()
        async with connection.channel(publisher_confirms=True) as channel:
            queue = await declare_code_job_topology(
                channel, target=compute_target
            )
            await channel.default_exchange.publish(
                Message(
                    body=job.model_dump_json().encode("utf-8"),
                    content_type="application/json",
                    delivery_mode=DeliveryMode.PERSISTENT,
                    message_id=message_id,
                ),
                routing_key=queue.name,
                mandatory=True,
            )
        return message_id
