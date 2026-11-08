from module_agent.literature.domain.search import LiteratureBundle
from module_agent.literature.application.run import LiteratureRunService
from module_agent.literature.application.agent import LiteratureAgent
from module_agent.literature.domain.recommendation import LiteratureRunPaper
from module_agent.literature.domain.run import LiteratureRun
from module_agent.shared.redaction import redact_sensitive_text
from module_agent.shared.execution_control import ExecutionStopped, run_with_control
from collections.abc import Awaitable, Callable
from module_agent.literature.domain.run import LiteratureRunStatus



class LiteratureRunExecutor:
    """执行并记录一次应用任务。"""
    def __init__(
        self,
        agent: LiteratureAgent,
        run_service: LiteratureRunService,
        *,
        execution_control: Callable[[int], Awaitable[bool]] | None = None,
    ) -> None:
        """初始化当前对象。"""
        self.agent = agent
        self.run_service = run_service
        self.execution_control = execution_control

    async def start(self, run_id: int) -> LiteratureRun:
        """启动当前流程。"""
        return await self.run_service.start_run(run_id)

    async def get_run(self, run_id: int) -> LiteratureRun:
        """获取对应记录。"""
        return await self.run_service.get_run(run_id)

    async def execute_started(
        self,
        run: LiteratureRun,
    ) -> LiteratureBundle:
        """执行当前用例。"""
        if run.id is None:
            raise ValueError("Started literature run is missing id")

        run_id = run.id

        try:
            request = run.request
            control = self.execution_control
            literature_bundle = await run_with_control(lambda:self.agent.run(request), (lambda:control(run_id)) if control is not None else None)
            
            profiles_by_identity = {
                (profile.source, profile.source_id): profile
                for profile in literature_bundle.method_profiles
            }
            
            assessments_by_identity = {
                (assessment.source, assessment.source_id): assessment
                for assessment in literature_bundle.relevance_assessments
            }
            run_papers: list[LiteratureRunPaper] = []

            for position, (selected, persisted) in enumerate(
                zip(
                    literature_bundle.selected_papers,
                    literature_bundle.persisted_papers,
                    strict=True,
                )
            ):
                if persisted.id is None:
                    raise RuntimeError("Persisted paper is missing id")

                assessment = assessments_by_identity.get(
                    (selected.source, selected.source_id)
                )
                if assessment is None:
                    raise RuntimeError(
                        "Selected paper is missing relevance assessment"
                    )

                run_papers.append(
                    LiteratureRunPaper(
                        paper_id=persisted.id,
                        position=position,
                        relevance_score=assessment.score,
                        relevance_reason=assessment.reason,
                        matched_terms=assessment.matched_terms,
                        integrity=selected.integrity,
                        method_profile=profiles_by_identity.get(
                            (selected.source, selected.source_id)
                        ),
                    )
                )

            await self.run_service.complete_run(
                run_id=run_id,
                search_queries=literature_bundle.search_queries,
                papers=run_papers,
                warnings=literature_bundle.warnings,
                source_metrics=literature_bundle.source_metrics,
                llm_metrics=literature_bundle.llm_metrics,
            )
        except ExecutionStopped:
            current = await self.run_service.get_run(run_id)
            if current.status is not LiteratureRunStatus.CANCELLED:
                await self.run_service.cancel_run(run_id)
            raise
        except Exception as exc:
            error_message = redact_sensitive_text(str(exc).strip() or type(exc).__name__)
            await self.run_service.fail_run(run_id, error_message)
            raise
        
        
        return literature_bundle

    async def execute(self, run_id: int) -> LiteratureBundle:
        """执行当前用例。"""
        run = await self.start(run_id)
        return await self.execute_started(run)
