from sqlalchemy.dialects.postgresql import JSONB

from module_agent.shared.database.base import Base
from module_agent.literature.adapters.database.models.selection import (
    PaperSelectionModel,
)


def test_paper_selection_model_is_registered_with_expected_columns() -> None:
    table = PaperSelectionModel.__table__

    assert "paper_selections" in Base.metadata.tables
    assert table.c.run_id.primary_key is True
    assert isinstance(table.c.selected_paper_ids.type, JSONB)
    assert table.c.selected_paper_ids.nullable is False
    assert table.c.code_requirements.nullable is True
    assert table.c.selected_at.nullable is False
    assert table.c.selected_at.type.timezone is True
    assert table.c.selected_at.server_default is not None


def test_paper_selection_model_cascades_when_run_is_deleted() -> None:
    foreign_key = next(iter(PaperSelectionModel.__table__.c.run_id.foreign_keys))

    assert foreign_key.target_fullname == "literature_runs.id"
    assert foreign_key.ondelete == "CASCADE"
