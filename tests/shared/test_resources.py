"""Resource discovery must respect process/container constraints."""

from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from module_agent.shared import resources


def prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    proc, cgroup = tmp_path / "proc", tmp_path / "cgroup"
    proc.mkdir()
    (proc / "self").mkdir()
    cgroup.mkdir()
    (proc / "meminfo").write_text("MemTotal: 8388608 kB\nMemAvailable: 6291456 kB\n")
    monkeypatch.setattr(resources.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(resources.os, "sched_getaffinity", lambda _: set(range(8)))
    monkeypatch.setattr(resources, "_gpu_resources", lambda: ("unavailable", []))
    monkeypatch.setattr(resources, "_sandbox_readiness", lambda _: (False, "not configured"))
    return proc, cgroup


def test_nested_cgroup_v2_limits_override_host_capacity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proc, cgroup = prepare(tmp_path, monkeypatch)
    (proc / "self/cgroup").write_text("0::/tenant/task\n")
    group = cgroup / "tenant/task"
    group.mkdir(parents=True)
    (group / "cpu.max").write_text("150000 100000")
    (group / "memory.max").write_text(str(2 * 1024**3))
    (group / "memory.current").write_text(str(512 * 1024**2))
    snapshot = resources.inspect_resources(tmp_path, proc_root=proc, cgroup_root=cgroup)
    assert snapshot.logical_cpu_count == 16
    assert snapshot.available_cpu_count == 1.5
    assert snapshot.memory_total_mb == 2048
    assert snapshot.memory_available_mb == 1536
    assert snapshot.gpu_status == "unavailable"


def test_cgroup_v1_and_zero_available_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proc, cgroup = prepare(tmp_path, monkeypatch)
    for controller in ("cpu", "memory"):
        (cgroup / controller).mkdir()
    (cgroup / "cpu/cpu.cfs_quota_us").write_text("50000")
    (cgroup / "cpu/cpu.cfs_period_us").write_text("100000")
    (cgroup / "memory/memory.limit_in_bytes").write_text(str(1024**3))
    (cgroup / "memory/memory.usage_in_bytes").write_text(str(1024**3))
    snapshot = resources.inspect_resources(tmp_path, proc_root=proc, cgroup_root=cgroup)
    assert snapshot.available_cpu_count == 0.5
    assert snapshot.memory_total_mb == 1024
    assert snapshot.memory_available_mb == 0


def test_parent_cgroup_limit_is_not_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proc, cgroup = prepare(tmp_path, monkeypatch)
    (proc / "self/cgroup").write_text("0::/tenant/task\n")
    group = cgroup / "tenant/task"
    group.mkdir(parents=True)
    (group / "cpu.max").write_text("400000 100000")
    (group.parent / "cpu.max").write_text("100000 100000")
    snapshot = resources.inspect_resources(tmp_path / "not-created" / "workspace", proc_root=proc, cgroup_root=cgroup)
    assert snapshot.available_cpu_count == 1
    assert snapshot.workspace_free_mb is not None


def test_unknown_memory_is_reported_as_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proc, cgroup = prepare(tmp_path, monkeypatch)
    (proc / "meminfo").unlink()
    snapshot = resources.inspect_resources(tmp_path, proc_root=proc, cgroup_root=cgroup)
    assert snapshot.memory_total_mb is None
    assert snapshot.memory_available_mb is None


def test_nvidia_query_parses_device_uuid_and_handles_unknown_free_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resources.shutil, "which", lambda _: "/fake/nvidia-smi")
    monkeypatch.setattr(resources.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout="0, GPU-test-123, NVIDIA Test, 8192, 6144\n1, GPU-test-456, Other, 4096, [N/A]\n",
    ))
    status, devices = resources._gpu_resources()
    assert status == "detected"
    assert [device.uuid for device in devices] == ["GPU-test-123", "GPU-test-456"]
    assert devices[0].memory_free_mb == 6144
    assert devices[1].memory_free_mb is None


def test_nvidia_timeout_is_not_claimed_as_no_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resources.shutil, "which", lambda _: "/fake/nvidia-smi")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("nvidia-smi", 2)

    monkeypatch.setattr(resources.subprocess, "run", timeout)
    assert resources._gpu_resources() == ("unavailable", [])
