"""Synthetic files and fake runners only: no network, Docker, torch or training."""

import asyncio
import ast
import hashlib
import json
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from module_agent.experiments import workspace as files
from module_agent.experiments.domain import (
    ExperimentBudget,
    ExperimentConsent,
    ExperimentMetrics,
    ExperimentPlan,
    ExperimentResult,
    ExperimentStatus,
    StepResult,
)
from module_agent.experiments.docker import DockerExperimentRunner
from module_agent.experiments.mnist import (
    build_m5_plan,
    environment_command,
    evaluation_command,
    structured_stdout,
    train_command,
)
from module_agent.experiments.service import ExperimentService
from module_agent.experiments.workspace import (
    ExperimentWorkspace,
    bounded_read,
    code_files,
    dataset_files,
    fingerprint,
    verify_commit,
)

IMAGE = "sha256:" + "a" * 64


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "verify_commit", lambda *_: None)
    # Deliberately tiny IDX fixture. Production RAW sizes remain 60k/10k.
    monkeypatch.setattr(
        files,
        "RAW",
        {
            "train-images-idx3-ubyte": (2051, 3, 28, 28),
            "train-labels-idx1-ubyte": (2049, 3),
            "t10k-images-idx3-ubyte": (2051, 2, 28, 28),
            "t10k-labels-idx1-ubyte": (2049, 2),
        },
    )
    repository, dataset = tmp_path / "repository", tmp_path / "dataset"
    for name in (
        "train.py",
        "test.py",
        "datasets.py",
        "ema.py",
        "transforms.py",
        "models/modelM3.py",
        "models/modelM5.py",
        "models/modelM7.py",
    ):
        path = repository / "code" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Synthetic source; never imported or executed\n")
    for name, header in files.RAW.items():
        path = dataset / "MNIST" / "raw" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = bytes(header[1] * (784 if len(header) == 4 else 1))
        path.write_bytes(struct.pack(">" + "I" * len(header), *header) + payload)
    workspace = ExperimentWorkspace(tmp_path)
    plan = ExperimentPlan(
        repository_path=repository,
        dataset_path=dataset,
        source_sha256=fingerprint(code_files(repository)),
        dataset_sha256=fingerprint(dataset_files(dataset)),
        image=IMAGE,
        budget=ExperimentBudget(gpu_uuid="GPU-fixture"),
        source_patch_note="Synthetic test fixture, not author code",
    )
    return workspace, plan


def consent(plan):
    return ExperimentConsent(
        plan_sha256=plan.digest(),
        execute_code=True,
        acknowledge_source_license=True,
        acknowledge_gpu_not_memory_capped=True,
    )


class FakeRunner:
    def __init__(self, workspace, *, fail_step=None, no_files=False, corrupt=None):
        self.workspace = workspace
        self.calls = []
        self.fail_step, self.no_files, self.corrupt = fail_step, no_files, corrupt

    async def execute(self, plan, name, argv):
        self.calls.append((name, argv))
        stdout = ""
        if name == "environment":
            stdout = 'MODULE_AGENT_ENV={"fixture":true}'
        elif name == "train" and not self.no_files:
            directory = self.workspace.run_directory(plan) / "outputs" / "pilot"
            directory.mkdir()
            rows = "0 0.5 85 0.2 99.00 99.00\n1 0.4 90 0.1 99.23 99.23\n"
            if self.corrupt == "epochs":
                rows = rows.splitlines()[0] + "\n"
            if self.corrupt == "nan":
                rows = rows.replace("0.4", "nan")
            (directory / f"log{plan.seed:03d}.out").write_text(rows)
            (directory / f"model{plan.seed:03d}.pth").write_bytes(
                b"synthetic-not-a-pytorch-checkpoint"
            )
        elif name == "evaluate":
            if not self.no_files:
                directory = self.workspace.run_directory(plan) / "outputs" / "pilot"
                wrong = list(range(77))
                if self.corrupt == "duplicates":
                    wrong[-1] = 0
                if self.corrupt == "range":
                    wrong[-1] = 10000
                (directory / f"wrong{plan.seed:03d}.txt").write_text(
                    "\n".join(map(str, wrong))
                )
            measured = {
                "evaluated_samples": 10000,
                "correct": 9923,
                "wrong": 77,
                "accuracy_percent": 9923 / 10000 * 100,
                "checkpoint_sha256": hashlib.sha256(
                    b"synthetic-not-a-pytorch-checkpoint"
                ).hexdigest(),
            }
            if self.corrupt == "measured":
                measured["evaluated_samples"] = 9999
            stdout = "MODULE_AGENT_EVAL=" + json.dumps(measured)
        return StepResult(
            name=name,
            exit_code=137 if name == self.fail_step else 0,
            stdout=stdout,
            duration_ms=1,
        )


def test_full_pilot_persists_steps_and_metrics_but_not_paper_success(prepared):
    workspace, plan = prepared
    runner = FakeRunner(workspace)
    result = asyncio.run(
        ExperimentService(workspace, runner).execute(plan, consent(plan))
    )
    assert result.status is ExperimentStatus.COMPLETED
    assert result.metrics.accuracy_percent == 99.23
    assert result.metrics.correct == 9923
    assert result.paper_reproduced is False
    assert result.comparison == "not_comparable_short_single_seed_pilot"
    directory = workspace.run_directory(plan)
    assert (
        ExperimentResult.model_validate_json((directory / "result.json").read_text())
        == result
    )
    assert (directory / "metrics.json").is_file()
    assert (directory / "environment.json").is_file()
    assert [name for name, _ in runner.calls] == ["environment", "train", "evaluate"]
    assert all(
        (directory / ("step-" + name + ".json")).exists() for name, _ in runner.calls
    )
    assert train_command(plan)[train_command(plan).index("--trials") + 1] == "1"
    assert "weights_only=True" in evaluation_command(plan)[-1]


def test_consent_binds_budget_image_and_sources_before_any_execution(prepared):
    workspace, plan = prepared
    runner = FakeRunner(workspace)
    service = ExperimentService(workspace, runner)
    changed = plan.model_copy(update={"image": "sha256:" + "b" * 64})
    with pytest.raises(ValueError, match="Authorization"):
        asyncio.run(service.execute(changed, consent(plan)))
    assert runner.calls == []
    assert not workspace.run_directory(plan).exists()


def test_inputs_changed_after_consent_are_rejected(prepared):
    workspace, plan = prepared
    (plan.repository_path / "code" / "train.py").write_text("# Changed after approval")
    runner = FakeRunner(workspace)
    with pytest.raises(ValueError, match="Inputs changed"):
        asyncio.run(ExperimentService(workspace, runner).execute(plan, consent(plan)))
    assert runner.calls == []


def test_existing_run_is_never_silently_reexecuted(prepared):
    workspace, plan = prepared
    runner = FakeRunner(workspace)
    service = ExperimentService(workspace, runner)
    asyncio.run(service.execute(plan, consent(plan)))
    with pytest.raises(FileExistsError):
        asyncio.run(service.execute(plan, consent(plan)))
    assert len(runner.calls) == 3


@pytest.mark.parametrize(
    "corrupt", ["epochs", "nan", "duplicates", "range", "measured"]
)
def test_invalid_metrics_cannot_complete_a_pilot(prepared, corrupt):
    workspace, plan = prepared
    result = asyncio.run(
        ExperimentService(workspace, FakeRunner(workspace, corrupt=corrupt)).execute(
            plan, consent(plan)
        )
    )
    assert result.status is ExperimentStatus.FAILED
    assert result.metrics is None and result.paper_reproduced is False


def test_exit_zero_without_training_artifacts_is_not_success(prepared):
    workspace, plan = prepared
    result = asyncio.run(
        ExperimentService(workspace, FakeRunner(workspace, no_files=True)).execute(
            plan, consent(plan)
        )
    )
    assert result.status is ExperimentStatus.FAILED
    assert result.metrics is None


def test_nonzero_exit_does_not_run_later_steps(prepared):
    workspace, plan = prepared
    runner = FakeRunner(workspace, fail_step="train")
    result = asyncio.run(
        ExperimentService(workspace, runner).execute(plan, consent(plan))
    )
    assert result.status is ExperimentStatus.FAILED
    assert "137" in result.error
    assert [name for name, _ in runner.calls] == ["environment", "train"]


def test_cancellation_persists_result_and_serializes_other_plans(prepared):
    workspace, plan = prepared
    runner = FakeRunner(workspace)
    started = asyncio.Event()

    async def wait(*_):
        started.set()
        await asyncio.sleep(60)

    runner.execute = wait

    async def exercise():
        service = ExperimentService(workspace, runner)
        task = asyncio.create_task(service.execute(plan, consent(plan)))
        await started.wait()
        other = plan.model_copy(update={"id": uuid4()})
        with pytest.raises(RuntimeError, match="already running"):
            await service.execute(other, consent(other))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    saved = json.loads((workspace.run_directory(plan) / "result.json").read_text())
    assert saved["status"] == "cancelled"
    with workspace.execution_lock():
        pass


def test_total_time_budget_persists_timeout(prepared):
    workspace, plan = prepared
    plan = plan.model_copy(
        update={"budget": plan.budget.model_copy(update={"timeout_seconds": 1})}
    )
    runner = FakeRunner(workspace)

    async def wait(*_):
        await asyncio.sleep(60)

    runner.execute = wait
    result = asyncio.run(
        ExperimentService(workspace, runner).execute(plan, consent(plan))
    )
    assert result.status is ExperimentStatus.TIMED_OUT


def test_snapshot_only_contains_frozen_code_data_and_separate_outputs(prepared):
    workspace, plan = prepared
    (plan.repository_path / "code" / "model.pyc").write_bytes(b"untrusted bytecode")
    directory = workspace.snapshot(plan)
    assert not (directory / "repository" / "code" / "model.pyc").exists()
    assert (directory / "repository" / "data").is_dir()
    original = (directory / "repository" / "code" / "train.py").read_bytes()
    (plan.repository_path / "code" / "train.py").write_text("# Later source edit")
    assert (directory / "repository" / "code" / "train.py").read_bytes() == original
    command = DockerExperimentRunner(workspace).command(
        plan, ["python", "-u", "train.py"], "module-agent-experiment-test"
    )
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--pull") + 1] == "never"
    assert command[command.index("--user") + 1] != "0:0"
    assert command[command.index("--gpus") + 1] == '"device=GPU-fixture"'
    assert "--privileged" not in command and not any(
        "docker.sock" in part for part in command
    )
    mounts = [
        command[index + 1] for index, value in enumerate(command) if value == "--mount"
    ]
    assert (
        len(mounts) == 3 and sum(value.endswith(",readonly") for value in mounts) == 2
    )


def test_no_path_traversal_source_links_or_symlink_output_reads(prepared, tmp_path):
    workspace, plan = prepared
    outside = tmp_path.parent
    with pytest.raises(ValueError, match="escapes"):
        workspace.input_directory(outside)
    (plan.repository_path / "code" / "link.py").symlink_to(
        plan.repository_path / "code" / "train.py"
    )
    with pytest.raises(ValueError, match="symlinks"):
        code_files(plan.repository_path)
    target = tmp_path / "link"
    target.symlink_to(plan.repository_path / "code" / "train.py")
    with pytest.raises(OSError):
        bounded_read(target, 1000)


@pytest.mark.parametrize("bad", ["header", "length", "labels"])
def test_idx_validation_rejects_corruption(prepared, bad):
    _, plan = prepared
    path = plan.dataset_path / "MNIST/raw/train-labels-idx1-ubyte"
    content = path.read_bytes()
    if bad == "header":
        content = b"\0" * 8 + content[8:]
    elif bad == "length":
        content = content[:-1]
    else:
        content = content[:-1] + b"\xff"
    path.write_bytes(content)
    with pytest.raises(ValueError):
        dataset_files(plan.dataset_path)


def test_builder_never_imports_sources_and_requires_reviewed_head(
    prepared, monkeypatch
):
    workspace, plan = prepared
    created = build_m5_plan(
        workspace,
        repository=plan.repository_path,
        dataset=plan.dataset_path,
        image=IMAGE,
        budget=plan.budget,
        patch_note="Reviewed patch",
    )
    assert created.source_sha256 == plan.source_sha256
    path = plan.repository_path / "code/datasets.py"
    path.write_text("import numpy as np\nx = np.int\n")
    with pytest.raises(ValueError, match="np.int"):
        build_m5_plan(
            workspace,
            repository=plan.repository_path,
            dataset=plan.dataset_path,
            image=IMAGE,
            budget=plan.budget,
            patch_note="Review needed",
        )


@pytest.mark.parametrize(
    "update",
    [
        {"image": "torch:latest"},
        {"epochs": 150},
        {"purpose": "paper_reproduced"},
        {"source_commit": "wrong"},
        {"network": True},
    ],
)
def test_plan_rejects_unreviewed_modes(prepared, update):
    _, plan = prepared
    with pytest.raises(ValidationError):
        ExperimentPlan.model_validate({**plan.model_dump(), **update})


def test_result_models_reject_unearned_success():
    with pytest.raises(ValidationError):
        ExperimentMetrics(
            correct=9999,
            wrong=2,
            accuracy_percent=99.99,
            completed_epochs=2,
            checkpoint_sha256="a" * 64,
        )
    with pytest.raises(ValidationError):
        ExperimentResult(
            plan_id=uuid4(), plan_sha256="a" * 64, status="completed", stage="finished"
        )
    with pytest.raises(ValidationError):
        ExperimentResult(
            plan_id=uuid4(),
            plan_sha256="a" * 64,
            status="failed",
            stage="stopped",
            paper_reproduced=True,
        )


def test_structured_evidence_and_probe_do_not_hide_missing_cuda():
    with pytest.raises(ValueError):
        structured_stdout("exit 0", "MODULE_AGENT_ENV=")
    with pytest.raises(ValueError):
        structured_stdout("P={}\nP={}", "P=")
    assert "torch.cuda.is_available()" in environment_command()[-1]
    assert "torch.ones(1,device='cuda')" in environment_command()[-1]


def test_generated_sandbox_scripts_are_valid_python_without_running_them(prepared):
    _, plan = prepared
    ast.parse(environment_command()[-1])
    module = ast.parse(evaluation_command(plan)[-1])
    assert "seen==10000" in evaluation_command(plan)[-1]
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "load_state_dict"
        for node in ast.walk(module)
    )


def test_output_budget_rejects_oversize_and_symlink(tmp_path):
    (tmp_path / "large").write_bytes(b"x" * 200)
    with pytest.raises(ValueError, match="budget"):
        DockerExperimentRunner._check_output_limit(tmp_path, 100)
    (tmp_path / "large").unlink()
    (tmp_path / "link").symlink_to(tmp_path.parent)
    with pytest.raises(ValueError, match="symlinks"):
        DockerExperimentRunner._check_output_limit(tmp_path, 1000)


def test_docker_cancellation_removes_owned_container(prepared, monkeypatch):
    workspace, plan = prepared
    workspace.snapshot(plan)
    process = SimpleNamespace(returncode=None, stdout=None, stderr=None)
    process.kill = lambda: setattr(process, "returncode", -9)
    started = asyncio.Event()

    async def wait():
        started.set()
        await asyncio.sleep(60)

    process.wait = wait
    ps = SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(b"", b"")))
    create = AsyncMock(side_effect=[ps, process])
    monkeypatch.setattr(
        "module_agent.experiments.docker.asyncio.create_subprocess_exec", create
    )
    runner = DockerExperimentRunner(workspace)
    runner._remove = AsyncMock()

    async def exercise():
        process.stdout = asyncio.StreamReader()
        process.stderr = asyncio.StreamReader()
        task = asyncio.create_task(
            runner.execute(plan, "train", ["python", "train.py"])
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    runner._remove.assert_awaited_once()
    assert runner._remove.await_args.args[0].startswith("module-agent-experiment-")
    assert process.returncode == -9


def test_cli_missing_consent_cannot_start_runner(tmp_path, capsys):
    from module_agent.cli.run_experiment import main

    with pytest.raises(SystemExit) as error:
        main(
            [
                "run",
                "--workspace-root",
                str(tmp_path),
                "--plan",
                "not-prepared.json",
                "--approve-sha256",
                "a" * 64,
            ]
        )
    assert error.value.code == 2
    assert "--execute-code" in capsys.readouterr().err


def test_perfect_evaluation_accepts_empty_wrong_file(prepared):
    workspace, plan = prepared
    runner = FakeRunner(workspace)
    asyncio.run(ExperimentService(workspace, runner).execute(plan, consent(plan)))
    directory = workspace.run_directory(plan) / "outputs/pilot"
    (directory / "wrong000.txt").write_text("")
    (directory / "log000.out").write_text(
        "0 0.1 98 0.01 100 100\n1 0.1 99 0.01 100 100\n"
    )
    metrics = workspace.collect(plan)
    assert (
        metrics.correct == 10000
        and metrics.wrong == 0
        and metrics.accuracy_percent == 100
    )


def test_owned_orphan_container_blocks_execution_instead_of_replaying(
    prepared, monkeypatch
):
    workspace, plan = prepared
    ps = SimpleNamespace(
        returncode=0, communicate=AsyncMock(return_value=(b"owned-container-id", b""))
    )
    create = AsyncMock(return_value=ps)
    monkeypatch.setattr(
        "module_agent.experiments.docker.asyncio.create_subprocess_exec", create
    )
    with pytest.raises(RuntimeError, match="previous owned"):
        asyncio.run(
            DockerExperimentRunner(workspace).execute(
                plan, "train", ["python", "train.py"]
            )
        )
    assert create.await_count == 1


def test_docker_logs_are_live_bounded_and_redacted(prepared, monkeypatch):
    workspace, plan = prepared
    workspace.snapshot(plan)
    runner = DockerExperimentRunner(workspace)
    runner._remove = AsyncMock()

    async def exercise():
        stdout, stderr = asyncio.StreamReader(), asyncio.StreamReader()
        stdout.feed_data(b"api_key=do-not-leak\n" + b"x" * 9000 + b"\n" + b"z" * 150000)
        stdout.feed_eof()
        stderr.feed_data(b"Bearer secret-value\n")
        stderr.feed_eof()
        process = SimpleNamespace(
            returncode=0, stdout=stdout, stderr=stderr, wait=AsyncMock(return_value=0)
        )
        ps = SimpleNamespace(
            returncode=0, communicate=AsyncMock(return_value=(b"", b""))
        )
        monkeypatch.setattr(
            "module_agent.experiments.docker.asyncio.create_subprocess_exec",
            AsyncMock(side_effect=[ps, process]),
        )
        return await runner.execute(plan, "train", ["python", "train.py"])

    result = asyncio.run(exercise())
    log = (workspace.run_directory(plan) / "execution.log").read_text()
    assert "do-not-leak" not in log and "secret-value" not in log
    assert "[REDACTED]" in log and "overlong log line omitted" in log
    assert result.output_truncated is True
    assert len(result.stdout) <= 131072
    runner._remove.assert_awaited_once()


def test_cli_plan_and_status_are_nonexecuting_entrypoints(
    prepared, monkeypatch, capsys
):
    from module_agent.cli.run_experiment import main

    workspace, plan = prepared
    output = workspace.root / "frozen-plan.json"
    args = [
        "plan",
        "--workspace-root",
        str(workspace.root),
        "--repository",
        str(plan.repository_path),
        "--dataset",
        str(plan.dataset_path),
        "--image",
        IMAGE,
        "--gpu-uuid",
        "GPU-fixture",
        "--patch-note",
        "Synthetic patch",
        "--output",
        str(output),
    ]
    assert main(args) == 0
    frozen = ExperimentPlan.model_validate_json(output.read_text())
    assert frozen.digest() in capsys.readouterr().out
    assert main(args) == 2  # Existing plans are never overwritten.
    asyncio.run(
        ExperimentService(workspace, FakeRunner(workspace)).execute(
            frozen, consent(frozen)
        )
    )
    assert (
        main(["status", "--workspace-root", str(workspace.root), "--plan", str(output)])
        == 0
    )


@pytest.mark.parametrize(
    "check_code,remaining", [(0, b""), (0, b"orphan-id"), (1, b"")]
)
def test_docker_cleanup_verifies_missing_container_and_detects_uncertain_state(
    prepared, monkeypatch, check_code, remaining
):
    workspace, _ = prepared
    remove = SimpleNamespace(returncode=1, wait=AsyncMock(return_value=1))
    check = SimpleNamespace(
        returncode=check_code, communicate=AsyncMock(return_value=(remaining, None))
    )
    create = AsyncMock(side_effect=[remove, check])
    monkeypatch.setattr(
        "module_agent.experiments.docker.asyncio.create_subprocess_exec", create
    )
    operation = DockerExperimentRunner(workspace)._remove(
        "module-agent-experiment-fixture"
    )
    if check_code == 0 and not remaining:
        asyncio.run(operation)
    else:
        with pytest.raises(RuntimeError, match="could not be verified"):
            asyncio.run(operation)
    assert create.await_args.args[-1] == "name=^/module-agent-experiment-fixture$"


def test_wrong_git_commit_cannot_be_claimed_as_the_reviewed_paper(
    prepared, monkeypatch
):
    _, plan = prepared
    # Exercise the real checker, rather than the fixture's no-op commit check.
    monkeypatch.setattr(
        files.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="wrong-commit")
    )
    with pytest.raises(ValueError, match="reviewed author commit"):
        verify_commit(plan.repository_path, plan.source_commit)
