from datetime import date

from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from module_agent.literature.adapters.database.models.paper import PaperModel


def test_paper_model_uses_expected_columns_and_types() -> None:
    table = PaperModel.__table__

    assert PaperModel.__tablename__ == "papers"
    assert isinstance(table.c.authors.type, JSONB)
    assert table.c.authors.nullable is False
    assert table.c.publication_date.type.python_type is date
    assert table.c.is_open_access.nullable is False
    assert table.c.cited_by_count.nullable is False


def test_paper_model_defines_source_and_doi_uniqueness() -> None:
    table = PaperModel.__table__
    constraint_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    doi_index = next(index for index in table.indexes if index.name == "uq_papers_doi")

    assert "uq_paper_source_source_id" in constraint_names
    assert doi_index.unique is True
    assert str(doi_index.dialect_options["postgresql"]["where"]) == "doi IS NOT NULL"


def test_paper_model_links_to_venue_with_set_null_delete() -> None:
    foreign_key = next(iter(PaperModel.__table__.c.venue_id.foreign_keys))

    assert foreign_key.target_fullname == "venues.id"
    assert foreign_key.ondelete == "SET NULL"
    assert PaperModel.venue.property.mapper.class_.__name__ == "VenueModel"
