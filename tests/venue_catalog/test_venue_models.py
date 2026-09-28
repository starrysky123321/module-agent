from sqlalchemy import Enum, UniqueConstraint

from module_agent.venue_catalog.adapters.database.models import (
    VenueAliasModel,
    VenueModel,
    VenueRankingModel,
)


def test_venue_models_use_expected_tables_and_relationships() -> None:
    assert VenueModel.__tablename__ == "venues"
    assert VenueAliasModel.__tablename__ == "venue_aliases"
    assert VenueRankingModel.__tablename__ == "venue_rankings"

    assert VenueModel.aliases.property.back_populates == "venue"
    assert VenueModel.rankings.property.back_populates == "venue"
    assert "delete-orphan" in VenueModel.aliases.property.cascade
    assert "delete-orphan" in VenueModel.rankings.property.cascade

    venue_constraint_names = {
        constraint.name
        for constraint in VenueModel.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert "uq_venue_name_type" in venue_constraint_names
    assert VenueModel.__table__.c.normalized_name.unique is not True


def test_venue_models_define_foreign_keys_and_unique_ranking() -> None:
    alias_foreign_key = next(iter(VenueAliasModel.__table__.c.venue_id.foreign_keys))
    ranking_foreign_key = next(
        iter(VenueRankingModel.__table__.c.venue_id.foreign_keys)
    )

    assert alias_foreign_key.target_fullname == "venues.id"
    assert alias_foreign_key.ondelete == "CASCADE"
    assert ranking_foreign_key.target_fullname == "venues.id"
    assert ranking_foreign_key.ondelete == "CASCADE"

    constraint_names = {
        constraint.name
        for constraint in VenueRankingModel.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert "uq_venue_ranking_edition_category" in constraint_names

    alias_constraint_names = {
        constraint.name
        for constraint in VenueAliasModel.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert "uq_venue_alias_per_venue" in alias_constraint_names
    assert VenueAliasModel.__table__.c.normalized_alias.unique is not True


def test_venue_type_enum_persists_domain_values() -> None:
    venue_type = VenueModel.__table__.c.venue_type.type

    assert isinstance(venue_type, Enum)
    assert venue_type.enums == ["conference", "journal"]
