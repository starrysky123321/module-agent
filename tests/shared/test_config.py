from pathlib import Path

import pytest
from pydantic import ValidationError

from module_agent.shared.config import AppSettings


def test_secret_can_be_loaded_from_file(tmp_path: Path) -> None:
    secret_file = tmp_path / "github-token"
    secret_file.write_text("secret-from-file\n", encoding="utf-8")

    settings = AppSettings(
        _env_file=None,
        github_token_file=secret_file,
    )

    assert settings.github_token == "secret-from-file"


def test_secret_rejects_direct_and_file_configuration(tmp_path: Path) -> None:
    secret_file = tmp_path / "github-token"
    secret_file.write_text("secret-from-file", encoding="utf-8")

    with pytest.raises(ValidationError, match="configure only one"):
        AppSettings(
            _env_file=None,
            github_token="direct-secret",
            github_token_file=secret_file,
        )


def test_secret_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="cannot read secret file"):
        AppSettings(
            _env_file=None,
            qwen_api_key_file=tmp_path / "missing",
        )


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


def test_literature_sources_reject_unknown_or_duplicate_names() -> None:
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, literature_sources=["unknown"])
    with pytest.raises(ValidationError):
        AppSettings(
            _env_file=None,
            literature_sources=["openalex", "openalex"],
        )


def test_completion_recovery_settings_parse_environment_values() -> None:
    settings = AppSettings(
        _env_file=None,
        completion_dead_letter_replay_limit="5",
        completion_dead_letter_retry_delay_ms="45000",
    )

    assert settings.completion_dead_letter_replay_limit == 5
    assert settings.completion_dead_letter_retry_delay_ms == 45_000


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("completion_dead_letter_replay_limit", 0),
        ("completion_dead_letter_replay_limit", 21),
        ("completion_dead_letter_retry_delay_ms", 999),
        ("completion_dead_letter_retry_delay_ms", 3_600_001),
    ],
)
def test_completion_recovery_settings_reject_unsafe_boundaries(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, **{field: value})


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
