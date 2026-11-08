from module_agent.literature.adapters.sources.crossref_integrity import (
    CrossrefPaperIntegrityChecker,
)
from module_agent.literature.adapters.sources.http_client import (
    literature_http_client_manager,
)
from module_agent.literature.application.integrity import PaperIntegrityService
from module_agent.shared.config import app_settings


def build_paper_integrity_service() -> PaperIntegrityService | None:
    """API 与 Worker 共用同一套有界核验策略。"""
    if not app_settings.literature_integrity_check_enabled:
        return None
    return PaperIntegrityService(
        CrossrefPaperIntegrityChecker(
            literature_http_client_manager.get_client(),
            timeout_seconds=app_settings.literature_integrity_timeout_seconds,
        ),
        budget_seconds=app_settings.literature_integrity_budget_seconds,
    )
