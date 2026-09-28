from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from module_agent.code.domain.artifact import CodeArtifact
from module_agent.literature.adapters.database.models.paper import PaperModel


class SqlAlchemyPaperCodeStatusWriter:
    """把 CodeArtifact 的仓库判断同步回论文记录。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.session_factory = session_factory

    async def write(self, artifacts: Sequence[CodeArtifact]) -> None:
        """在独立短事务中幂等更新每篇已处理论文。"""
        async with self.session_factory() as session:
            async with session.begin():
                for artifact in artifacts:
                    model = await session.get(PaperModel, artifact.paper_id)
                    if model is None:
                        continue
                    model.code_availability = artifact.code_availability.value
                    model.code_repository_url = (
                        str(artifact.repository_url)
                        if artifact.repository_url is not None
                        else None
                    )
                    model.code_repository_confidence = (
                        artifact.confidence
                        if artifact.repository_url is not None
                        else None
                    )
                    model.code_repository_evidence = [
                        evidence.model_dump(mode="json")
                        for evidence in artifact.evidence
                    ]
