from typing import Protocol, TypeVar


InputT = TypeVar("InputT", contravariant=True)
OutputT = TypeVar("OutputT", covariant=True)


class Agent(Protocol[InputT, OutputT]):
    """协调该 Agent 的业务流程。"""

    async def run(self, input_data: InputT) -> OutputT:
        """处理输入并返回 Agent 结果。"""
        ...
