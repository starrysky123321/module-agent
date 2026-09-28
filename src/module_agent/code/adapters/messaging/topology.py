"""RabbitMQ topology for asynchronous Code Agent execution."""

from aio_pika.abc import AbstractChannel, AbstractQueue

from module_agent.code.domain.jobs import ComputeTarget


def code_queue_name(target: ComputeTarget) -> str:
    """Return the stable queue name for a compute pool."""
    return f"code.jobs.{target.value}.v1"


async def declare_code_job_topology(
    channel: AbstractChannel,
    *,
    target: ComputeTarget,
    delivery_limit: int = 3,
) -> AbstractQueue:
    """Declare a quorum job queue and its dead-letter queue."""
    queue_name = code_queue_name(target)
    dead_queue_name = f"{queue_name}.dead"
    await channel.declare_queue(
        dead_queue_name,
        durable=True,
        arguments={"x-queue-type": "quorum"},
    )
    return await channel.declare_queue(
        queue_name,
        durable=True,
        arguments={
            "x-queue-type": "quorum",
            "x-delivery-limit": delivery_limit,
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": dead_queue_name,
        },
    )


async def declare_code_completion_topology(
    channel: AbstractChannel,
) -> AbstractQueue:
    """Declare the completion queue and its dead-letter queue."""
    queue_name = "code.completed.v1"
    dead_queue_name = "code.completed.dead.v1"
    await channel.declare_queue(
        dead_queue_name,
        durable=True,
        arguments={"x-queue-type": "quorum"},
    )
    return await channel.declare_queue(
        queue_name,
        durable=True,
        arguments={
            "x-queue-type": "quorum",
            "x-delivery-limit": 3,
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": dead_queue_name,
        },
    )
