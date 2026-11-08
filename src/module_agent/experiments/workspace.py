"""Owned snapshots and bounded, symlink-safe metric collection. No torch imports."""

import hashlib
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import stat
import struct
import subprocess

from module_agent.experiments.domain import ExperimentMetrics, ExperimentPlan

RAW = {
    "train-images-idx3-ubyte": (2051, 60000, 28, 28),
    "train-labels-idx1-ubyte": (2049, 60000),
    "t10k-images-idx3-ubyte": (2051, 10000, 28, 28),
    "t10k-labels-idx1-ubyte": (2049, 10000),
}


def bounded_read(path: Path, maximum: int) -> bytes:
    """Reject symlinks/devices and growth before returning untrusted bytes."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise ValueError(f"Invalid or oversized experiment file: {path.name}")
        data = handle.read(maximum + 1)
        if len(data) > maximum:
            raise ValueError("Experiment file grew past its limit")
        return data


def code_files(repository: Path) -> dict[str, bytes]:
    code = repository / "code"
    if code.is_symlink() or not code.is_dir():
        raise ValueError("Repository must contain a real code directory")
    files = {}
    for path in sorted(code.rglob("*")):
        if path.is_symlink():
            raise ValueError("Source symlinks are not supported")
        if path.is_file() and path.suffix == ".py":
            if len(files) >= 100:
                raise ValueError("Too many source files")
            files[path.relative_to(repository).as_posix()] = bounded_read(path, 100_000)
    required = {
        "code/train.py",
        "code/test.py",
        "code/datasets.py",
        "code/ema.py",
        "code/transforms.py",
        "code/models/modelM3.py",
        "code/models/modelM5.py",
        "code/models/modelM7.py",
    }
    if not required <= files.keys():
        raise ValueError("M5 source files are missing")
    return files


def dataset_files(directory: Path) -> dict[str, bytes]:
    if directory.is_symlink():
        raise ValueError("Dataset directory cannot be a symlink")
    files = {}
    for filename, header in RAW.items():
        path = directory / "MNIST" / "raw" / filename
        if any(parent.is_symlink() for parent in path.parents):
            raise ValueError("Dataset parent symlinks are not supported")
        raw = bounded_read(path, 48_000_000)
        size = len(header) * 4
        expected_bytes = header[1] * (784 if len(header) == 4 else 1)
        if (
            len(raw) != size + expected_bytes
            or struct.unpack(">" + "I" * len(header), raw[:size]) != header
        ):
            raise ValueError(f"Invalid MNIST IDX file: {filename}")
        if len(header) == 2 and any(label > 9 for label in raw[size:]):
            raise ValueError("Invalid MNIST label")
        files["MNIST/raw/" + filename] = raw
    return files


def fingerprint(files: dict[str, bytes]) -> str:
    entries = {
        name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())
    }
    return hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()


def verify_commit(repository: Path, expected: str) -> None:
    # A curated archive is verified against code-owned hashes, never a user manifest.
    from module_agent.experiments.recipe import COMMIT, verify_curated_sources

    if not (repository / ".git").exists():
        if expected != COMMIT or not verify_curated_sources(code_files(repository)):
            raise ValueError("Source snapshot differs from the reviewed author commit")
        return
    head = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    if head.stdout.strip() != expected:
        raise ValueError("Repository HEAD is not the reviewed author commit")


class ExperimentWorkspace:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)

    def input_directory(self, value: Path) -> Path:
        if not value.is_absolute() or value.is_symlink():
            raise ValueError("Input must be an absolute, non-symlink directory")
        path = value.resolve(strict=True)
        if not path.is_relative_to(self.root) or path == self.root or not path.is_dir():
            raise ValueError("Experiment input escapes its configured workspace")
        if any(parent.is_symlink() for parent in value.parents):
            raise ValueError("Input parent symlinks are not supported")
        return path

    def run_directory(self, plan: ExperimentPlan) -> Path:
        path = self.root / "experiment-runs" / str(plan.id)
        if path.parent.is_symlink() or path.is_symlink():
            raise ValueError("Run directory symlinks are not supported")
        return path

    @contextmanager
    def execution_lock(self, *, worker: bool = False):
        """One local workspace executes at most one experiment at a time."""
        directory = self.root / "experiment-runs"
        if directory.is_symlink():
            raise ValueError("Run root cannot be a symlink")
        directory.mkdir(exist_ok=True, mode=0o700)
        fd = os.open(
            directory / (".worker.lock" if worker else ".executor.lock"),
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
        )
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("Executor lock must be a regular file")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError(
                    "Another experiment is already running in this workspace"
                ) from error
            yield
        finally:
            os.close(fd)

    def snapshot(self, plan: ExperimentPlan) -> Path:
        repository = self.input_directory(plan.repository_path)
        verify_commit(repository, plan.source_commit)
        sources = code_files(repository)
        data = dataset_files(self.input_directory(plan.dataset_path))
        if (
            fingerprint(sources) != plan.source_sha256
            or fingerprint(data) != plan.dataset_sha256
        ):
            raise ValueError("Inputs changed after the experiment plan was approved")
        run = self.run_directory(plan)
        run.mkdir(parents=True, exist_ok=False, mode=0o700)
        for base, files in ((run / "repository", sources), (run / "data", data)):
            for name, content in files.items():
                destination = base / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                parent = destination.parent
                while parent.is_relative_to(base):
                    parent.chmod(0o755)
                    parent = parent.parent
                destination.write_bytes(content)
                destination.chmod(0o444)
        for name in ("data", "logs"):
            (run / "repository" / name).mkdir(mode=0o755)
        outputs = run / "outputs"
        outputs.mkdir(mode=0o770)
        if os.getuid() == 0:
            os.chown(outputs, 65534, 65534)
        self.save_json(run / "plan.json", plan.model_dump(mode="json"))
        return run

    @staticmethod
    def save_json(path: Path, data: object) -> None:
        temporary = path.with_suffix(".pending")
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def collect(self, plan: ExperimentPlan) -> ExperimentMetrics:
        directory = self.run_directory(plan) / "outputs" / "pilot"
        if directory.is_symlink():
            raise ValueError("Result directory cannot be a symlink")
        rows = (
            bounded_read(directory / f"log{plan.seed:03d}.out", 1_000_000)
            .decode()
            .splitlines()
        )
        rows = [row.split() for row in rows if row.strip()]
        if len(rows) != plan.epochs or any(len(row) != 6 for row in rows):
            raise ValueError("Training did not produce the expected epoch records")
        for epoch, row in enumerate(rows):
            if int(row[0]) != epoch:
                raise ValueError("Training epoch sequence is incomplete")
            if not all(math.isfinite(float(value)) for value in row):
                raise ValueError("Training metrics contain NaN or infinity")
            if any(not 0 <= float(row[index]) <= 100 for index in (2, 4, 5)):
                raise ValueError("Training accuracy is out of range")
            if float(row[5]) < float(row[4]) or (
                epoch and float(row[5]) < float(rows[epoch - 1][5])
            ):
                raise ValueError(
                    "Best checkpoint accuracy is inconsistent across epochs"
                )
        wrong = (
            bounded_read(directory / f"wrong{plan.seed:03d}.txt", 100_000)
            .decode()
            .split()
        )
        indices = [int(value) for value in wrong]
        if len(indices) != len(set(indices)) or any(
            index < 0 or index >= 10000 for index in indices
        ):
            raise ValueError("Wrong-image indices are invalid")
        checkpoint = bounded_read(
            directory / f"model{plan.seed:03d}.pth", 64 * 1024 * 1024
        )
        if not checkpoint:
            raise ValueError("Checkpoint is empty")
        accuracy = (10000 - len(indices)) / 100
        if abs(float(rows[-1][5]) - accuracy) > 0.0011:
            raise ValueError("Evaluation does not match the best training checkpoint")
        return ExperimentMetrics(
            correct=10000 - len(indices),
            wrong=len(indices),
            accuracy_percent=accuracy,
            completed_epochs=len(rows),
            checkpoint_sha256=hashlib.sha256(checkpoint).hexdigest(),
        )
