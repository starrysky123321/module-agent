import asyncio
from pathlib import Path
from typing import cast

import pytest

from module_agent.validation.adapters.docker import DockerSandboxRunner


class FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = list(chunks)
        self.read_calls = 0

    async def read(self, size: int = -1) -> bytes:
        assert size == 8192
        self.read_calls += 1
        return self.chunks.pop(0)


def stream(chunks: list[bytes]) -> asyncio.StreamReader:
    return cast(asyncio.StreamReader, FakeStream([*chunks, b""]))


class FakeProcess:
    def __init__(self, stdout: list[bytes], stderr: list[bytes]) -> None:
        self.stdout = stream(stdout)
        self.stderr = stream(stderr)
        self.returncode: int | None = None

    async def wait(self) -> int:
        self.returncode = 0
        return 0


def test_limited_reader_rejects_negative_limit() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        asyncio.run(DockerSandboxRunner._read_stream_limited(None, -1))


def test_limited_reader_accepts_missing_stream() -> None:
    result = asyncio.run(
        DockerSandboxRunner._read_stream_limited(None, 10)
    )

    assert result == (b"", False)


def test_limited_reader_preserves_output_at_exact_limit() -> None:
    fake_stream = FakeStream([b"abc", b"de", b""])

    result = asyncio.run(
        DockerSandboxRunner._read_stream_limited(
            cast(asyncio.StreamReader, fake_stream),
            5,
        )
    )

    assert result == (b"abcde", False)
    assert fake_stream.read_calls == 3


def test_limited_reader_truncates_output_over_limit() -> None:
    result = asyncio.run(
        DockerSandboxRunner._read_stream_limited(
            stream([b"abcdef"]),
            3,
        )
    )

    assert result == (b"abc", True)


def test_limited_reader_continues_draining_after_limit() -> None:
    fake_stream = FakeStream([b"abc", b"def", b"ghi", b""])

    result = asyncio.run(
        DockerSandboxRunner._read_stream_limited(
            cast(asyncio.StreamReader, fake_stream),
            4,
        )
    )

    assert result == (b"abcd", True)
    assert fake_stream.read_calls == 4


def test_zero_limit_discards_but_still_drains_stream() -> None:
    fake_stream = FakeStream([b"abc", b"def", b""])

    result = asyncio.run(
        DockerSandboxRunner._read_stream_limited(
            cast(asyncio.StreamReader, fake_stream),
            0,
        )
    )

    assert result == (b"", True)
    assert fake_stream.read_calls == 3


def test_communicate_limited_caps_combined_retained_output() -> None:
    runner = DockerSandboxRunner(Path.cwd(), image="sandbox:local")
    process = cast(
        asyncio.subprocess.Process,
        FakeProcess([b"abcdef"], [b"uvwxyz"]),
    )

    stdout, stderr, truncated = asyncio.run(
        runner._communicate_limited(process, 7)
    )

    assert stdout == b"abcd"
    assert stderr == b"uvw"
    assert truncated is True


def test_output_redaction_covers_flags_assignments_and_bearer_tokens() -> None:
    output = (
        b"token=visible api_key:also-visible "
        b"Authorization: Bearer third-value cli-secret"
    )

    redacted = DockerSandboxRunner._decode_and_redact(
        output,
        ["program", "--password", "cli-secret"],
    )

    assert "visible" not in redacted
    assert "also-visible" not in redacted
    assert "third-value" not in redacted
    assert "cli-secret" not in redacted
    assert "[REDACTED]" in redacted
