"""Explicitly authorized, fixed-origin downloads and an isolated image build."""

import asyncio
import gzip
import hashlib
import io
from pathlib import Path

from module_agent.experiments.domain import ExperimentPlan
from module_agent.experiments.jobs import PilotProposal
from module_agent.experiments.mnist import build_m5_plan
from module_agent.experiments.recipe import COMMIT, DATA, DOCKERFILE, PATCHED_DATASET, SOURCES
from module_agent.experiments.workspace import ExperimentWorkspace, bounded_read, verify_commit

IMAGE_TAG = "module-agent-mnist-m5:runtime-v1"


def safe_target(root: Path, target: Path) -> Path:
    """Cache files must remain in our private root, including every parent."""
    if not target.is_relative_to(root) or any(part.is_symlink() for part in (target, *target.parents)):
        raise ValueError("缓存路径不能通过符号链接离开实验工作区")
    return target


async def command(*arguments: str, timeout: float = 180) -> str:
    """Bound subprocess output and always stop our subprocess on cancellation."""
    process = await asyncio.create_subprocess_exec(*arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    output = bytearray()
    assert process.stdout is not None
    try:
        async with asyncio.timeout(timeout):
            while chunk := await process.stdout.read(8192):
                output.extend(chunk)
                if len(output) > 65536:
                    del output[:-65536]
            code = await process.wait()
            if code:
                raise RuntimeError(f"{arguments[0]} 执行失败（退出码 {code}）：" + output.decode(errors="replace")[-1000:])
            return output.decode(errors="replace").strip()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def download(url: str, target: Path, digest: str) -> bytes:
    if target.exists():
        data = bounded_read(target, 16_000_000)
        if hashlib.sha256(data).hexdigest() == digest:
            return data
        raise ValueError("已缓存文件校验失败；请由运维检查缓存，不自动覆盖。")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".partial")
    if temporary.is_symlink():
        raise ValueError("下载临时路径不能是符号链接")
    await command("curl", "--fail", "--location", "--silent", "--show-error", "--proto", "=https",
                  "--proto-redir", "=https", "--connect-timeout", "15", "--max-time", "90",
                  "--max-filesize", "16000000", "--retry", "1", "--output", str(temporary), url)
    data = bounded_read(temporary, 16_000_000)
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("下载文件 SHA256 与固定配方不符；已拒绝执行。")
    temporary.replace(target)
    return data


async def prepare_m5(root: Path, proposal: PilotProposal, image_override: str = "") -> ExperimentPlan:
    """No arbitrary repository install hooks; Python source is only copied/hashed."""
    cache = root / "reviewed-m5-v1"
    safe_target(root, cache)
    repository, dataset = cache / "source", cache / "data"
    cache.mkdir(parents=True, exist_ok=True)
    for name, digest in SOURCES.items():
        content = await download(f"https://raw.githubusercontent.com/ansh941/MnistSimpleCNN/{COMMIT}/{name}", safe_target(root, cache / "downloads" / name), digest)
        if name == "code/datasets.py":
            content = content.replace(b"ys.astype(np.int)", b"ys.astype(np.int64)")
            if hashlib.sha256(content).hexdigest() != PATCHED_DATASET:
                raise ValueError("兼容性补丁与已审核结果不一致")
        target = safe_target(root, repository / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise ValueError("源码缓存不能含符号链接")
        target.write_bytes(content)
    verify_commit(repository, COMMIT)
    for name, digest in DATA.items():
        compressed = await download(f"https://storage.googleapis.com/cvdf-datasets/mnist/{name}.gz", safe_target(root, cache / "downloads" / (name + ".gz")), digest)
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
            raw = stream.read(48_000_001)
        if len(raw) > 48_000_000:
            raise ValueError("MNIST 解压结果超过上限")
        target = safe_target(root, dataset / "MNIST" / "raw" / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise ValueError("数据缓存不能含符号链接")
        target.write_bytes(raw)
    if image_override:
        image = await command("docker", "image", "inspect", image_override, "--format", "{{.Id}}")
        if image != image_override:
            raise ValueError("Worker 镜像覆盖值必须是已缓存的不可变 sha256 ID")
    else:
        # Only our tiny recipe enters the build context, never project/.env/source.
        context = safe_target(root, cache / "image")
        context.mkdir(exist_ok=True)
        safe_target(root, context / "Dockerfile").write_text(DOCKERFILE)
        await command("docker", "build", "--tag", IMAGE_TAG, str(context), timeout=1100)
        image = await command("docker", "image", "inspect", IMAGE_TAG, "--format", "{{.Id}}")
    plan = build_m5_plan(ExperimentWorkspace(root), repository=repository, dataset=dataset,
                         image=image, budget=proposal.budget,
                         patch_note="固定作者提交的 8 个源码文件逐一校验 SHA256；唯一兼容性修改为 np.int → np.int64；未加载上游序列化数据。")
    return plan.model_copy(update={"id": proposal.id})
