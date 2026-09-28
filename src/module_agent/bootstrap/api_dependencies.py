from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends
from typing import Annotated

from module_agent.literature.application.agent import LiteratureAgent
from module_agent.venue_catalog.domain.repository import VenueRepository
from module_agent.venue_catalog.application.quality import VenueQualityService
from module_agent.shared.config import app_settings
from module_agent.literature.application.search import LiteratureSearchService
from module_agent.shared.database.session import (
    async_session_factory,
    get_database_session,
)
from module_agent.venue_catalog.adapters.database.repository import SqlAlchemyVenueRepository
from module_agent.venue_catalog.domain.cache import VenueCache
from module_agent.literature.domain.repositories.paper import PaperRepository
from module_agent.venue_catalog.adapters.cache import RedisVenueCache
from module_agent.shared.cache.redis import redis_client
from module_agent.literature.adapters.database.repositories.paper import (
    SqlAlchemyPaperRepository,
)
from module_agent.literature.adapters.database.repositories.code_status import (
    SqlAlchemyPaperCodeStatusWriter,
)
from module_agent.literature.application.catalog import PaperCatalogService
from module_agent.literature.adapters.database.repositories.run import SqlAlchemyLiteratureRunRepository
from module_agent.literature.application.run import LiteratureRunService
from module_agent.literature.domain.repositories.run import LiteratureRunRepository
from module_agent.literature.application.execution import LiteratureRunExecutor
from module_agent.literature.application.dispatch import LiteratureRunDispatcher
from module_agent.literature.domain.jobs import LiteratureJobQueue
from module_agent.shared.messaging.rabbitmq import (
    rabbitmq_connection_manager,
)
from module_agent.literature.adapters.messaging.job_queue import (
    RabbitMQLiteratureJobQueue,
)
from module_agent.literature.adapters.sources.registry import LITERATURE_SOURCE_REGISTRY
from module_agent.literature.application.result import LiteratureResultService
from module_agent.literature.domain.query import LiteratureQueryPlanner
from module_agent.literature.domain.source import LiteratureSource

from module_agent.shared.llm.qwen_client import qwen_client_manager
from module_agent.bootstrap.factories.query_planner import build_literature_query_planner
from module_agent.literature.domain.ranking import PaperRelevanceScorer
from module_agent.bootstrap.factories.relevance_scorer import (
    build_paper_relevance_scorer,
)
from module_agent.bootstrap.factories.method_extractor import build_paper_method_extractor
from module_agent.literature.domain.method import PaperMethodExtractor
from module_agent.literature.adapters.database.repositories.selection import SqlAlchemyPaperSelectionRepository
from module_agent.literature.application.selection import PaperSelectionService
from module_agent.literature.domain.repositories.selection import PaperSelectionRepository
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from module_agent.shared.checkpoint.postgres import (
    postgres_checkpointer_manager,
)
from module_agent.code.application.agent import CodeAgent
from module_agent.code.application.run import CodeRunService
from module_agent.code.adapters.database.repositories.run import (
    TransactionalCodeRunRepository,
)
from module_agent.validation.application.agent import ValidationAgent
from module_agent.validation.application.run import ValidationRunService
from module_agent.validation.adapters.database.repositories.run import (
    TransactionalValidationRunRepository,
)
from module_agent.supervision.application.agent import SupervisorAgent
from langgraph.graph.state import CompiledStateGraph
from module_agent.workflow.graph import ModuleBuildWorkflow
from module_agent.workflow.service import ModuleWorkflowService
from module_agent.workflow.coordinator import (
    ModuleWorkflowCoordinator,
)
from module_agent.workflow.adapters.database.repository import (
    TransactionalModuleWorkflowRunRepository,
)
from module_agent.workflow.lifecycle_service import (
    ModuleWorkflowLifecycleService,
)
from module_agent.workflow.adapters.database.node_execution import (
    SqlAlchemyWorkflowNodeExecutionRepository,
)
from module_agent.bootstrap.factories.code_agent import build_code_agent
from module_agent.bootstrap.factories.validation_agent import (
    build_validation_agent,
)
from module_agent.code.adapters.github_client import github_client_manager
from module_agent.workflow.code_input import (
    SelectedPaperCodeInputLoader,
)
from module_agent.bootstrap.factories.supervisor_agent import (
    build_supervisor_agent,
)
from module_agent.shared.decision.typesafe_client import (
    typesafe_client_manager,
)
from module_agent.supervision.adapters.database.observation_sink import (
    SqlAlchemySupervisorObservationSink,
)
from module_agent.supervision.domain import SupervisorObservationSink
from module_agent.supervision.domain import (
    SupervisorObservationStatsReader,
)
from module_agent.supervision.adapters.database.repositories.observation import (
    SqlAlchemySupervisorObservationRepository,
)
from module_agent.supervision.application.observation_query import (
    SupervisorObservationQueryService,
)
from module_agent.code.domain.jobs import CodeJobQueue
from module_agent.code.adapters.messaging.job_queue import RabbitMQCodeJobQueue



def get_paper_selection_repository(session: Annotated[AsyncSession, Depends(get_database_session)]) -> SqlAlchemyPaperSelectionRepository:
    """获取对应记录。"""
    return SqlAlchemyPaperSelectionRepository(session)

def get_paper_method_extractor() -> PaperMethodExtractor | None:
    """获取对应记录。"""
    return build_paper_method_extractor(
        mode=app_settings.literature_method_extractor,
        qwen_model=app_settings.qwen_model,
        qwen_client_manager=qwen_client_manager,
        timeout_seconds=app_settings.qwen_call_timeout_seconds,
    )

def get_paper_relevance_scorer() -> PaperRelevanceScorer:
    """获取对应记录。"""
    return build_paper_relevance_scorer(
        mode=app_settings.literature_relevance_scorer,
        qwen_model=app_settings.qwen_model,
        qwen_client_manager=qwen_client_manager,
        timeout_seconds=app_settings.qwen_call_timeout_seconds,
    )


def get_literature_query_planner() -> LiteratureQueryPlanner:
    """获取对应记录。"""
    return build_literature_query_planner(
        mode=app_settings.literature_query_planner,
        qwen_model=app_settings.qwen_model,
        qwen_client_manager=qwen_client_manager,
        timeout_seconds=app_settings.qwen_call_timeout_seconds,
    )

def get_literature_search_service() -> LiteratureSearchService:
    """获取对应记录。"""
    sources: list[LiteratureSource] = [
        LITERATURE_SOURCE_REGISTRY[name]
        for name in app_settings.literature_sources
    ]
    return LiteratureSearchService(sources)


def get_venue_repository(session: Annotated[AsyncSession, Depends(get_database_session)])  -> SqlAlchemyVenueRepository:
    """获取对应记录。"""
    return SqlAlchemyVenueRepository(session)


def get_paper_repository(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> SqlAlchemyPaperRepository:
    """获取对应记录。"""
    return SqlAlchemyPaperRepository(session)

def get_venue_cache() -> VenueCache:
    """获取对应记录。"""
    return RedisVenueCache(redis_client)

def get_venue_quality_service(repository: Annotated[VenueRepository, Depends(get_venue_repository)], cache: Annotated[VenueCache, Depends(get_venue_cache)]) -> VenueQualityService:
    """获取对应记录。"""
    return VenueQualityService(repository, cache)


def get_paper_catalog_service(
    repository: Annotated[PaperRepository, Depends(get_paper_repository)],
) -> PaperCatalogService:
    """获取对应记录。"""
    return PaperCatalogService(repository)

def get_literature_agent(
    search_service: Annotated[LiteratureSearchService, Depends(get_literature_search_service)],
    venue_quality_service: Annotated[VenueQualityService, Depends(get_venue_quality_service)],
    paper_catalog_service: Annotated[
        PaperCatalogService,
        Depends(get_paper_catalog_service),
    ],
    relevance_scorer: Annotated[
        PaperRelevanceScorer,
        Depends(get_paper_relevance_scorer),
    ],
    query_planner: Annotated[LiteratureQueryPlanner, Depends(get_literature_query_planner)],
    method_extractor: Annotated[PaperMethodExtractor | None, Depends(get_paper_method_extractor)],
) -> LiteratureAgent:
    """获取对应记录。"""
    return LiteratureAgent(
        search_service=search_service,
        venue_quality_service=venue_quality_service,
        query_planner=query_planner,
        relevance_scorer=relevance_scorer,
        paper_catalog_service=paper_catalog_service,
        method_extractor=method_extractor,
    )


def get_literature_run_repository(
    session: Annotated[AsyncSession,
    Depends(get_database_session)],
) -> SqlAlchemyLiteratureRunRepository:
    """获取对应记录。"""
    return SqlAlchemyLiteratureRunRepository(session)


def get_literature_run_service(
    repository: Annotated[
        LiteratureRunRepository,
        Depends(get_literature_run_repository),
    ],
) -> LiteratureRunService:
    """获取对应记录。"""
    return LiteratureRunService(repository)

def get_literature_run_executor(
    agent: Annotated[
        LiteratureAgent,
        Depends(get_literature_agent),
    ],
    run_service: Annotated[
        LiteratureRunService,
        Depends(get_literature_run_service),
    ],
) -> LiteratureRunExecutor:
    """获取对应记录。"""
    return LiteratureRunExecutor(agent, run_service)



def get_literature_job_queue() -> LiteratureJobQueue:
    """获取对应记录。"""
    return RabbitMQLiteratureJobQueue(
        rabbitmq_connection_manager
    )


def get_literature_run_dispatcher(
    run_service: Annotated[
        LiteratureRunService,
        Depends(get_literature_run_service),
    ],
    job_queue: Annotated[
        LiteratureJobQueue,
        Depends(get_literature_job_queue),
    ],
) -> LiteratureRunDispatcher:
    """获取对应记录。"""
    return LiteratureRunDispatcher(run_service, job_queue)


def get_literature_result_service(
      run_repository: Annotated[
          LiteratureRunRepository,
          Depends(get_literature_run_repository),
      ],
      paper_repository: Annotated[
          PaperRepository,
          Depends(get_paper_repository),
      ],
  ) -> LiteratureResultService:
    """获取对应记录。"""
    return LiteratureResultService(
        paper_repository=paper_repository,
        run_repository=run_repository,
    )
    


def get_paper_selection_service(
    paper_selection_repository: Annotated[PaperSelectionRepository, Depends(get_paper_selection_repository)],
    literature_run_repository: Annotated[LiteratureRunRepository, Depends(get_literature_run_repository)],
) -> PaperSelectionService:
    """获取对应记录。"""
    return PaperSelectionService(
        paper_selection_repository=paper_selection_repository,
        literature_run_repository=literature_run_repository,
    )
    
    
def get_langgraph_checkpointer() -> AsyncPostgresSaver:
    """获取对应记录。"""
    return postgres_checkpointer_manager.get_checkpointer()



def get_code_agent() -> CodeAgent:
    """获取对应记录。"""
    return build_code_agent(
        github_client=github_client_manager.get_client(),
        github_token=app_settings.github_token,
        github_api_version=app_settings.github_api_version,
        qwen_client_manager=qwen_client_manager,
        qwen_model=app_settings.qwen_model,
        workspace_root=app_settings.code_workspace_root,
        git_timeout_seconds=app_settings.git_clone_timeout_seconds,
        confidence_threshold=(
            app_settings.code_repository_confidence_threshold
        ),
        search_limit=app_settings.code_repository_search_limit,
        pdf_max_bytes=app_settings.code_pdf_max_bytes,
        pdf_timeout_seconds=app_settings.code_pdf_timeout_seconds,
        pdf_parse_timeout_seconds=(
            app_settings.code_pdf_parse_timeout_seconds
        ),
        pdf_max_pages=app_settings.code_pdf_max_pages,
        pdf_parse_memory_bytes=(
            app_settings.code_pdf_parse_memory_bytes
        ),
        landing_page_max_bytes=app_settings.code_landing_page_max_bytes,
    )
    
    
def get_code_input_loader(
    paper_repository: Annotated[
        PaperRepository,
        Depends(get_paper_repository),
    ],
    literature_run_repository: Annotated[
        LiteratureRunRepository,
        Depends(get_literature_run_repository),
    ],
) -> SelectedPaperCodeInputLoader:
    """获取对应记录。"""
    return SelectedPaperCodeInputLoader(
        paper_repository=paper_repository,
        literature_run_repository=literature_run_repository,
    )


def get_validation_agent() -> ValidationAgent:
    """获取对应记录。"""
    return build_validation_agent(
        workspace_root=app_settings.code_workspace_root,
        sandbox_image=app_settings.validation_sandbox_image,
        git_timeout_seconds=(
            app_settings.validation_git_timeout_seconds
        ),
    )


def get_code_run_repository() -> TransactionalCodeRunRepository:
    """获取对应记录。"""
    return TransactionalCodeRunRepository(async_session_factory)


def get_code_job_queue() -> CodeJobQueue:
    """Return the RabbitMQ resource-aware Code Agent queue."""
    return RabbitMQCodeJobQueue(rabbitmq_connection_manager)


def get_code_run_service(
    agent: Annotated[CodeAgent, Depends(get_code_agent)],
    repository: Annotated[
        TransactionalCodeRunRepository,
        Depends(get_code_run_repository),
    ],
) -> CodeRunService:
    """获取对应记录。"""
    return CodeRunService(
        agent,
        repository,
        SqlAlchemyPaperCodeStatusWriter(async_session_factory),
    )


def get_validation_run_repository() -> TransactionalValidationRunRepository:
    """获取对应记录。"""
    return TransactionalValidationRunRepository(async_session_factory)


def get_validation_run_service(
    agent: Annotated[ValidationAgent, Depends(get_validation_agent)],
    repository: Annotated[
        TransactionalValidationRunRepository,
        Depends(get_validation_run_repository),
    ],
) -> ValidationRunService:
    """获取对应记录。"""
    return ValidationRunService(agent, repository)


def get_supervisor_observation_sink() -> SupervisorObservationSink:
    """获取对应记录。"""
    return SqlAlchemySupervisorObservationSink(async_session_factory)


def get_supervisor_observation_stats_reader(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> SqlAlchemySupervisorObservationRepository:
    """获取对应记录。"""
    return SqlAlchemySupervisorObservationRepository(session)


def get_supervisor_observation_query_service(
    reader: Annotated[
        SupervisorObservationStatsReader,
        Depends(get_supervisor_observation_stats_reader),
    ],
) -> SupervisorObservationQueryService:
    """获取对应记录。"""
    return SupervisorObservationQueryService(
        reader,
        readiness_minimum_observations=(
            app_settings.jev_readiness_minimum_observations
        ),
        readiness_minimum_success_rate=(
            app_settings.jev_readiness_minimum_success_rate
        ),
    )


def get_supervisor_agent(
    observation_sink: Annotated[
        SupervisorObservationSink,
        Depends(get_supervisor_observation_sink),
    ],
) -> SupervisorAgent:
    """获取对应记录。"""
    return build_supervisor_agent(
        mode=app_settings.supervisor_policy,
        typesafe_client_manager=typesafe_client_manager,
        confidence_threshold=(
            app_settings.jev_confidence_threshold
        ),
        observation_sink=observation_sink,
    )


def get_module_workflow_run_repository(
) -> TransactionalModuleWorkflowRunRepository:
    """获取对应记录。"""
    return TransactionalModuleWorkflowRunRepository(
        async_session_factory
    )


def get_module_workflow_lifecycle_service(
    repository: Annotated[
        TransactionalModuleWorkflowRunRepository,
        Depends(get_module_workflow_run_repository),
    ],
) -> ModuleWorkflowLifecycleService:
    """获取对应记录。"""
    return ModuleWorkflowLifecycleService(
        repository,
        default_timeout_seconds=app_settings.workflow_timeout_seconds,
    )


def get_workflow_node_execution_repository(
) -> SqlAlchemyWorkflowNodeExecutionRepository:
    """获取对应记录。"""
    return SqlAlchemyWorkflowNodeExecutionRepository(
        async_session_factory
    )

def get_module_build_graph(
    literature_dispatcher: Annotated[
        LiteratureRunDispatcher,
        Depends(get_literature_run_dispatcher),
    ],
    code_agent: Annotated[
        CodeAgent,
        Depends(get_code_agent),
    ],
    validation_agent: Annotated[
        ValidationAgent,
        Depends(get_validation_agent),
    ],
    supervisor_agent: Annotated[
        SupervisorAgent,
        Depends(get_supervisor_agent),
    ],
    checkpointer: Annotated[
        AsyncPostgresSaver,
        Depends(get_langgraph_checkpointer),
    ],
    code_input_loader: Annotated[
        SelectedPaperCodeInputLoader,
        Depends(get_code_input_loader),
    ],
    code_run_service: Annotated[
        CodeRunService,
        Depends(get_code_run_service),
    ],
    validation_run_service: Annotated[
        ValidationRunService,
        Depends(get_validation_run_service),
    ],
    lifecycle_service: Annotated[
        ModuleWorkflowLifecycleService,
        Depends(get_module_workflow_lifecycle_service),
    ],
    node_execution_repository: Annotated[
        SqlAlchemyWorkflowNodeExecutionRepository,
        Depends(get_workflow_node_execution_repository),
    ],
    code_job_queue: Annotated[
        CodeJobQueue,
        Depends(get_code_job_queue),
    ],

) -> CompiledStateGraph:
    
    """获取对应记录。"""
    workflow = ModuleBuildWorkflow(
        literature_dispatcher=literature_dispatcher,
        code_agent=code_agent,
        validation_agent=validation_agent,
        supervisor_agent=supervisor_agent,
        checkpointer=checkpointer,
        code_input_loader=code_input_loader,
        code_run_service=code_run_service,
        validation_run_service=validation_run_service,
        lifecycle_service=lifecycle_service,
        node_execution_recorder=node_execution_repository,
        code_job_queue=code_job_queue,
    )
    return workflow.build()

def get_module_workflow_service(
    graph: Annotated[
        CompiledStateGraph,
        Depends(get_module_build_graph),
    ],
    lifecycle_service: Annotated[
        ModuleWorkflowLifecycleService,
        Depends(get_module_workflow_lifecycle_service),
    ],
) -> ModuleWorkflowService:
    """获取对应记录。"""
    return ModuleWorkflowService(graph, lifecycle_service)



def get_module_workflow_coordinator(
    run_service: Annotated[
        LiteratureRunService,
        Depends(get_literature_run_service),
    ],
    workflow_service: Annotated[
        ModuleWorkflowService,
        Depends(get_module_workflow_service),
    ],
    selection_service: Annotated[
        PaperSelectionService,
        Depends(get_paper_selection_service),
    ],
) -> ModuleWorkflowCoordinator:
    """获取对应记录。"""
    return ModuleWorkflowCoordinator(
        workflow_service=workflow_service,
        run_service=run_service,
        selection_service=selection_service,    
    )
