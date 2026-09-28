from sqlalchemy import BigInteger

from module_agent.supervision.adapters.database.models.observation import (
    SupervisorFailureObservationModel,
)


def test_observation_model_has_run_foreign_key_and_query_indexes() -> None:
    table = SupervisorFailureObservationModel.__table__
    run_column = table.c.literature_run_id
    foreign_key = next(iter(run_column.foreign_keys))

    assert isinstance(table.c.id.type, BigInteger)
    assert foreign_key.target_fullname == "literature_runs.id"
    assert foreign_key.ondelete == "CASCADE"
    assert run_column.index is True
    assert table.c.failure_category.index is True
    assert table.c.created_at.index is True


def test_jev_result_columns_are_nullable_for_failed_calls() -> None:
    table = SupervisorFailureObservationModel.__table__

    for name in (
        "jev_disposition",
        "confidence",
        "retry_probability",
        "stop_probability",
        "model",
        "request_id",
        "latency_ms",
        "agrees",
        "meets_confidence_threshold",
    ):
        assert table.c[name].nullable is True
