from sqlalchemy.dialects.postgresql import JSONB, UUID

from module_agent.code.adapters.database.models.run import (
    CodeRunArtifactModel,
    CodeRunModel,
)
from module_agent.validation.adapters.database.models.run import (
    ValidationRunModel,
    ValidationRunReportModel,
)


def test_code_run_tables_have_idempotency_and_trace_fields() -> None:
    table = CodeRunModel.__table__
    constraints = {constraint.name for constraint in table.constraints}

    assert "uq_code_run_execution" in constraints
    assert "ck_code_run_attempt" in constraints
    assert isinstance(table.c.trace_id.type, UUID)
    assert isinstance(table.c.request.type, JSONB)
    assert CodeRunArtifactModel.__table__.c.artifact.nullable is False


def test_validation_run_tables_have_idempotency_and_trace_fields() -> None:
    table = ValidationRunModel.__table__
    constraints = {constraint.name for constraint in table.constraints}

    assert "uq_validation_run_execution" in constraints
    assert "ck_validation_run_attempt" in constraints
    assert isinstance(table.c.trace_id.type, UUID)
    assert isinstance(table.c.request.type, JSONB)
    assert ValidationRunReportModel.__table__.c.report.nullable is False
