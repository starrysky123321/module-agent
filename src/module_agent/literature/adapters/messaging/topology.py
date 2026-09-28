from aio_pika.abc import AbstractChannel, AbstractQueue

async def declare_literature_topology(
    channel: AbstractChannel,
    queue_name: str = "literature.jobs.v2",
    dead_queue_name: str = "literature.jobs.dead.v1",
    delivery_limit: int = 3,
) -> AbstractQueue:
    """声明文献主队列、重试队列和交换机。"""
    await declare_literature_dead_queue(
        channel,
        dead_queue_name,
    )

    return await channel.declare_queue(
        queue_name,
        durable=True,
        arguments={
            "x-queue-type": "quorum",
            "x-delivery-limit": delivery_limit,
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": dead_queue_name,
            "x-delayed-retry-type": "failed",
            "x-delayed-retry-min": 1000,
            "x-delayed-retry-max": 30000,
        },
    )


async def declare_literature_dead_queue(
    channel: AbstractChannel,
    dead_queue_name: str = "literature.jobs.dead.v1",
) -> AbstractQueue:
    """声明文献任务死信队列。"""
    return await channel.declare_queue(
        dead_queue_name,
        durable=True,
        arguments={"x-queue-type": "quorum"},
    )
