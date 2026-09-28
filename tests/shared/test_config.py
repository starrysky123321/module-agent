from pathlib import Path

import pytest
from pydantic import ValidationError

from module_agent.shared.config import AppSettings


def test_code_agent_settings_parse_environment_style_values() -> None:
    settings = AppSettings(
        _env_file=None,
        code_workspace_root="./tmp/code-workspaces",
        code_repository_confidence_threshold="0.8",
        code_repository_search_limit="6",
        git_clone_timeout_seconds="45",
    )

    assert settings.code_workspace_root == Path("./tmp/code-workspaces")
    assert settings.code_repository_confidence_threshold == 0.8
    assert settings.code_repository_search_limit == 6
    assert settings.git_clone_timeout_seconds == 45.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("code_repository_confidence_threshold", -0.1),
        ("code_repository_confidence_threshold", 1.1),
        ("code_repository_search_limit", 0),
        ("code_repository_search_limit", 101),
        ("git_clone_timeout_seconds", 0),
        ("git_clone_timeout_seconds", 1801),
    ],
)
def test_code_agent_settings_reject_invalid_boundaries(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, **{field: value})


def test_jev_settings_parse_environment_style_values() -> None:
    settings = AppSettings(
        _env_file=None,
        supervisor_policy="jev_shadow",
        typesafe_api_key="test-key",
        typesafe_model="jev-latest",
        typesafe_timeout_seconds="4.5",
        jev_confidence_threshold="0.85",
        jev_readiness_minimum_observations="50",
        jev_readiness_minimum_success_rate="0.9",
    )

    assert settings.supervisor_policy == "jev_shadow"
    assert settings.typesafe_api_key == "test-key"
    assert settings.typesafe_model == "jev-latest"
    assert settings.typesafe_timeout_seconds == 4.5
    assert settings.jev_confidence_threshold == 0.85
    assert settings.jev_readiness_minimum_observations == 50
    assert settings.jev_readiness_minimum_success_rate == 0.9


def test_jev_guarded_is_a_supported_policy_mode() -> None:
    settings = AppSettings(
        _env_file=None,
        supervisor_policy="jev_guarded",
    )

    assert settings.supervisor_policy == "jev_guarded"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("supervisor_policy", "jev"),
        ("typesafe_timeout_seconds", 0),
        ("typesafe_timeout_seconds", 31),
        ("jev_confidence_threshold", -0.1),
        ("jev_confidence_threshold", 1.1),
        ("jev_readiness_minimum_observations", 0),
        ("jev_readiness_minimum_success_rate", -0.1),
        ("jev_readiness_minimum_success_rate", 1.1),
    ],
)
def test_jev_settings_reject_invalid_values(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, **{field: value})
