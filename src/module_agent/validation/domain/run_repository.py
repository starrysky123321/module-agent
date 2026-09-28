from typing import Protocol

from module_agent.validation.domain.run import ValidationRun


class ValidationRunRepository(Protocol):
    """提供数据持久化访问能力。"""
    async def get_by_id(self, run_id: int) -> ValidationRun | None:
        """获取对应记录。"""
        ...

    async def get_by_execution(
        self,
        literature_run_id: int,
        attempt: int,
    ) -> ValidationRun | None:
        """获取对应记录。"""
        ...

    async def save(self, run: ValidationRun) -> ValidationRun:
        """保存当前记录。"""
        ...

    async def list_by_literature_run(
        self,
        literature_run_id: int,
    ) -> list[ValidationRun]:
        """列出符合条件的记录。"""
        ...
