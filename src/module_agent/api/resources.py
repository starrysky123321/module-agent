"""Authenticated resource discovery and resource-budget admission."""

from functools import partial
from pathlib import Path
from typing import Annotated
import asyncio

from fastapi import APIRouter, Depends, HTTPException

from module_agent.shared.config import app_settings
from module_agent.shared.resources import ResourceSnapshot, inspect_resources
from module_agent.validation.domain.request import ValidationMode, ValidationPolicy


resources_router = APIRouter(prefix="/system", tags=["system-resources"])


async def get_resource_snapshot() -> ResourceSnapshot:
    """Run bounded filesystem and device probes outside the HTTP event loop."""
    return await asyncio.to_thread(partial(
        inspect_resources,
        Path(app_settings.code_workspace_root),
        sandbox_image=app_settings.validation_sandbox_image,
    ))


@resources_router.get("/resources", response_model=ResourceSnapshot)
async def get_resources(
    snapshot: Annotated[ResourceSnapshot, Depends(get_resource_snapshot)],
) -> ResourceSnapshot:
    return snapshot


def validate_resource_budget(policy: ValidationPolicy, snapshot: ResourceSnapshot) -> None:
    """Check requested bounds against a fresh local snapshot, without reserving."""
    errors = []
    if policy.cpu_limit > snapshot.available_cpu_count:
        errors.append("CPU 上限超过当前环境可用 CPU。")
    if snapshot.memory_available_mb is not None and policy.memory_limit_mb > snapshot.memory_available_mb:
        errors.append("内存上限超过当前环境可用内存。")
    if policy.workspace_limit_mb is not None and policy.temporary_storage_mb > policy.memory_limit_mb:
        errors.append("沙箱临时空间上限不能超过内存预算。")
    if policy.workspace_limit_mb is not None and snapshot.workspace_free_mb is not None and policy.workspace_limit_mb > snapshot.workspace_free_mb:
        errors.append("工作区预算超过当前磁盘剩余空间。")
    if policy.mode is ValidationMode.SANDBOX:
        if not snapshot.sandbox_ready:
            errors.append(snapshot.sandbox_reason)
        if policy.compute_target.value == "gpu":
            visible = {device.uuid for device in snapshot.gpus}
            if not policy.gpu_device_ids or not set(policy.gpu_device_ids).issubset(visible):
                errors.append("选择的 GPU 在当前执行环境中不可用。")
    if errors:
        raise HTTPException(status_code=422, detail=" ".join(errors))


async def admit_requested_resource_budget(policy: ValidationPolicy | None) -> None:
    """Recheck explicitly budgeted new tasks; preserve legacy API behavior."""
    if policy is not None and policy.workspace_limit_mb is not None:
        validate_resource_budget(policy, await get_resource_snapshot())


@resources_router.post("/resources/validate", response_model=ResourceSnapshot)
async def check_resource_budget(
    policy: ValidationPolicy,
    snapshot: Annotated[ResourceSnapshot, Depends(get_resource_snapshot)],
) -> ResourceSnapshot:
    validate_resource_budget(policy, snapshot)
    return snapshot
