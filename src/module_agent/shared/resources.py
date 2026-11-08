"""Read the resources visible to this Agent service without changing the host."""

import csv
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Literal

from pydantic import BaseModel, Field


MIB = 1024 * 1024


class GpuResource(BaseModel):
    """One NVIDIA device visible to the current execution environment."""

    index: int
    uuid: str
    name: str
    memory_total_mb: int | None = None
    memory_free_mb: int | None = None


class ResourceSnapshot(BaseModel):
    """An observation, not a reservation or a description of the browser PC."""

    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    scope: Literal["container", "wsl", "host"]
    logical_cpu_count: int
    available_cpu_count: float
    memory_total_mb: int | None = None
    memory_available_mb: int | None = None
    workspace_total_mb: int | None = None
    workspace_free_mb: int | None = None
    gpu_status: Literal["detected", "not_detected", "unavailable"]
    gpus: list[GpuResource] = Field(default_factory=list)
    sandbox_ready: bool = False
    sandbox_reason: str = ""
    warnings: list[str] = Field(default_factory=list)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def _positive_int(value: str) -> int | None:
    try:
        number = int(value)
        return number if number > 0 else None
    except ValueError:
        return None


def _cgroup_paths(proc_root: Path, root: Path) -> list[Path]:
    """Include nested limits as well as namespace-root v1/v2 constraints."""
    paths = {root, root / "cpu", root / "cpu,cpuacct", root / "memory"}
    for line in _read(proc_root / "self/cgroup").splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        controllers = parts[1].split(",") if parts[1] else [""]
        if "cpu" in controllers:
            controllers.append("cpu,cpuacct")
        for name in controllers:
            if name not in {"", "cpu", "cpu,cpuacct", "memory"}:
                continue
            base = root / name if name else root
            candidate = (base / parts[2].lstrip("/")).resolve()
            if not candidate.is_relative_to(base.resolve()):
                continue
            while candidate.is_relative_to(base.resolve()):
                paths.add(candidate)
                if candidate == base.resolve():
                    break
                candidate = candidate.parent
    return sorted(paths)


def _gpu_resources() -> tuple[Literal["detected", "not_detected", "unavailable"], list[GpuResource]]:
    executable = shutil.which("nvidia-smi")
    if not executable and Path("/usr/lib/wsl/lib/nvidia-smi").is_file():
        executable = "/usr/lib/wsl/lib/nvidia-smi"
    if not executable:
        return "unavailable", []
    try:
        result = subprocess.run(
            [executable, "--query-gpu=index,uuid,name,memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        if result.returncode:
            return "unavailable", []
        devices = []
        for row in csv.reader(result.stdout.splitlines()):
            if len(row) != 5:
                continue
            index, uuid, name, total, free = (item.strip() for item in row)
            devices.append(GpuResource(
                index=int(index), uuid=uuid, name=name,
                memory_total_mb=_positive_int(total),
                memory_free_mb=int(free) if free.isdigit() else None,
            ))
        return ("detected" if devices else "not_detected"), devices
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return "unavailable", []


def _sandbox_readiness(image: str) -> tuple[bool, str]:
    if not image.strip():
        return False, "未配置 VALIDATION_SANDBOX_IMAGE，当前只能静态验证。"
    executable = shutil.which("docker")
    if not executable:
        return False, "当前执行环境没有 Docker CLI，沙箱不可用。"
    try:
        result = subprocess.run(
            [executable, "image", "inspect", image, "--format", "{{.Id}}"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        if result.returncode == 0:
            return True, "已连接 Docker，配置的沙箱镜像在本机可用。"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False, "Docker 未就绪或配置的沙箱镜像不存在。"


def inspect_resources(
    workspace_root: Path,
    *,
    sandbox_image: str = "",
    proc_root: Path = Path("/proc"),
    cgroup_root: Path = Path("/sys/fs/cgroup"),
) -> ResourceSnapshot:
    """Detect visible capacity, respecting CPU affinity and cgroup limits."""
    logical = os.cpu_count() or 1
    try:
        cpu = float(min(logical, len(os.sched_getaffinity(0))))
    except (AttributeError, OSError):
        cpu = float(logical)
    memory = {}
    for line in _read(proc_root / "meminfo").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] in {"MemTotal:", "MemAvailable:"}:
            value = int(fields[1]) if fields[1].isdigit() else None
            if value is not None:
                memory[fields[0][:-1]] = value * 1024
    total = memory.get("MemTotal")
    available = memory.get("MemAvailable")
    for directory in _cgroup_paths(proc_root, cgroup_root):
        maximum = _read(directory / "cpu.max").split()
        if len(maximum) == 2:
            quota, period = _positive_int(maximum[0]), _positive_int(maximum[1])
        else:
            quota = _positive_int(_read(directory / "cpu.cfs_quota_us"))
            period = _positive_int(_read(directory / "cpu.cfs_period_us"))
        if quota is not None and period is not None:
            cpu = min(cpu, quota / period)
        limit = _positive_int(_read(directory / "memory.max"))
        usage_text = _read(directory / "memory.current")
        if limit is None:
            limit = _positive_int(_read(directory / "memory.limit_in_bytes"))
            usage_text = _read(directory / "memory.usage_in_bytes")
        if limit is not None and limit < (1 << 60):
            total = min(total, limit) if total is not None else limit
            if usage_text.isdigit():
                remaining = max(0, limit - int(usage_text))
                available = min(available, remaining) if available is not None else remaining
    if total is not None and available is not None:
        available = min(total, available)

    warnings = [
        "检测的是运行 Agent 的当前环境，不是访问网页的电脑；快照不会预留资源。",
        "分布式部署时本接口不代表其他 Worker 节点的资源。",
        "CPU/内存为沙箱执行限额；工作区采用用量监测，超限终止，不是文件系统硬配额。",
    ]
    workspace = workspace_root.resolve()
    while not workspace.exists() and workspace != workspace.parent:
        workspace = workspace.parent
    disk_total = disk_free = None
    try:
        disk = shutil.disk_usage(workspace)
        disk_total, disk_free = disk.total // MIB, disk.free // MIB
    except OSError:
        warnings.append("无法读取代码工作区所在磁盘的剩余空间。")
    gpu_status, gpus = _gpu_resources()
    if gpu_status == "unavailable":
        warnings.append("当前环境无法查询 NVIDIA GPU；这不代表宿主机没有显卡。")
    sandbox_ready, sandbox_reason = _sandbox_readiness(sandbox_image)
    scope: Literal["container", "wsl", "host"] = "container" if Path("/.dockerenv").exists() else "wsl" if "microsoft" in platform.release().lower() else "host"
    return ResourceSnapshot(
        scope=scope,
        logical_cpu_count=logical,
        available_cpu_count=math.floor(cpu * 1000) / 1000,
        memory_total_mb=total // MIB if total is not None else None,
        memory_available_mb=available // MIB if available is not None else None,
        workspace_total_mb=disk_total, workspace_free_mb=disk_free,
        gpu_status=gpu_status, gpus=gpus,
        sandbox_ready=sandbox_ready, sandbox_reason=sandbox_reason,
        warnings=warnings,
    )
