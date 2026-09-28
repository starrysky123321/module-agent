from pathlib import Path

import pytest

from module_agent.validation.adapters.docker import DockerSandboxRunner
from module_agent.validation.domain.request import (
    ValidationMode,
    ValidationPolicy,
)
from module_agent.validation.domain.sandbox import SandboxExecutionRequest


def make_request(
    repository: Path,
    *,
    allow_network: bool = False,
    working_directory: str = ".",
) -> SandboxExecutionRequest:
    return SandboxExecutionRequest(
        repository_path=repository,
        argv=["python", "--version"],
        working_directory=working_directory,
        policy=ValidationPolicy(
            mode=ValidationMode.SANDBOX,
            allow_network=allow_network,
            memory_limit_mb=512,
            cpu_limit=0.5,
        ),
    )


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"image": "  "}, "image"),
        ({"image": "sandbox", "docker_executable": ""}, "executable"),
        ({"image": "sandbox", "pids_limit": 0}, "PIDs limit"),
    ],
)
def test_docker_runner_rejects_invalid_constructor_configuration(
    tmp_path: Path,
    updates: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        DockerSandboxRunner(tmp_path, **updates)  # type: ignore[arg-type]


def test_build_command_applies_security_and_resource_limits(
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "workspaces"
    repository = allowed_root / "repository with spaces"
    repository.mkdir(parents=True)
    runner = DockerSandboxRunner(
        allowed_root,
        image="validation-python:local",
        pids_limit=64,
    )

    command = runner._build_command(
        make_request(repository, working_directory="examples/demo"),
        "validation-test",
    )

    image_index = command.index("validation-python:local")
    assert command[:2] == ["docker", "run"]
    assert command[image_index + 1 :] == ["python", "--version"]
    assert command[command.index("--name") + 1] == "validation-test"
    assert command[command.index("--pull") + 1] == "never"
    assert "--rm" in command[:image_index]
    assert "--init" in command[:image_index]
    assert "--read-only" in command[:image_index]
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert command[command.index("--security-opt") + 1] == (
        "no-new-privileges"
    )
    assert command[command.index("--pids-limit") + 1] == "64"
    assert command[command.index("--memory") + 1] == "512m"
    assert command[command.index("--memory-swap") + 1] == "512m"
    assert command[command.index("--cpus") + 1] == "0.5"
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--workdir") + 1] == (
        "/workspace/repository/examples/demo"
    )
    assert command[command.index("--user") + 1] == "65534:65534"
    assert command[command.index("--mount") + 1] == (
        f"type=bind,source={repository.resolve()},"
        "target=/workspace/repository,readonly"
    )


def test_build_command_omits_network_none_when_explicitly_allowed(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    runner = DockerSandboxRunner(tmp_path, image="sandbox:local")

    command = runner._build_command(
        make_request(repository, allow_network=True),
        "validation-test",
    )

    assert "--network" not in command


def test_build_command_rejects_blank_container_name(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    runner = DockerSandboxRunner(tmp_path, image="sandbox:local")

    with pytest.raises(ValueError, match="Container name"):
        runner._build_command(make_request(repository), "  ")


def test_build_command_rejects_missing_repository(tmp_path: Path) -> None:
    runner = DockerSandboxRunner(tmp_path, image="sandbox:local")

    with pytest.raises(ValueError, match="existing directory"):
        runner._build_command(
            make_request(tmp_path / "missing"),
            "validation-test",
        )


def test_build_command_rejects_repository_outside_root(
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "workspaces"
    outside = tmp_path / "outside"
    allowed_root.mkdir()
    outside.mkdir()
    runner = DockerSandboxRunner(allowed_root, image="sandbox:local")

    with pytest.raises(ValueError, match="escapes allowed root"):
        runner._build_command(make_request(outside), "validation-test")


def test_build_command_rejects_symlink_escape(tmp_path: Path) -> None:
    allowed_root = tmp_path / "workspaces"
    outside = tmp_path / "outside"
    allowed_root.mkdir()
    outside.mkdir()
    link = allowed_root / "repository-link"
    link.symlink_to(outside, target_is_directory=True)
    runner = DockerSandboxRunner(allowed_root, image="sandbox:local")

    with pytest.raises(ValueError, match="escapes allowed root"):
        runner._build_command(make_request(link), "validation-test")
