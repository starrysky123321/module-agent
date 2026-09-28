from pathlib import Path

import pytest

from module_agent.shared.config import (
    AppSettings,
    validate_runtime_security,
)


def production_settings(**overrides: object) -> AppSettings:
    values: dict[str, object] = {
        "app_env": "production",
        "database_url": (
            "postgresql+asyncpg://agent:strong-db@db:5432/agent"
        ),
        "rabbitmq_url": "amqp://agent:strong-mq@mq:5672/agent",
        "langgraph_database_url": (
            "postgresql://agent:strong-db@db:5432/agent"
        ),
        "code_workspace_root": Path("/var/lib/module-agent/workspaces"),
        "api_auth_token": "a-secure-production-token-that-is-long-enough",
        "literature_query_planner": "rule",
        "literature_relevance_scorer": "rule",
        "literature_method_extractor": "off",
        "supervisor_policy": "rule",
    }
    values.update(overrides)
    return AppSettings(_env_file=None, **values)  # type: ignore[arg-type]


def test_safe_production_settings_are_accepted() -> None:
    validate_runtime_security(production_settings())


def test_development_password_is_rejected_in_production() -> None:
    settings = production_settings(
        database_url=(
            "postgresql+asyncpg://agent:module_agent_dev@db:5432/agent"
        )
    )

    with pytest.raises(RuntimeError, match="development password"):
        validate_runtime_security(settings)


def test_enabled_external_decision_provider_requires_key() -> None:
    settings = production_settings(supervisor_policy="jev_shadow")

    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY"):
        validate_runtime_security(settings)


def test_latest_sandbox_image_is_rejected() -> None:
    settings = production_settings(
        validation_sandbox_image="python:latest"
    )

    with pytest.raises(RuntimeError, match="latest tag"):
        validate_runtime_security(settings)


def test_short_api_token_is_rejected() -> None:
    settings = production_settings(api_auth_token="too-short")

    with pytest.raises(RuntimeError, match="API_AUTH_TOKEN"):
        validate_runtime_security(settings)
