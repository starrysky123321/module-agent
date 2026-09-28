import asyncio
import ipaddress
import multiprocessing
import re
import socket
from contextlib import suppress
from io import BytesIO
from math import ceil
from multiprocessing.connection import Connection
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from pypdf import PdfReader

from module_agent.code.domain.errors import (
    InvalidPdfContentError,
    PdfDownloadError,
    PdfParseError,
    PdfParseTimeoutError,
    PdfResourceLimitError,
    PdfTooLargeError,
    UnsafePdfUrlError,
)
from module_agent.code.domain.request import CodePaperInput

MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
MAX_PDF_PAGES = 200
MAX_PDF_LINKS = 100
MAX_PDF_TEXT_CHARACTERS = 2_000_000
MAX_PDF_ANNOTATIONS = 5_000
MAX_PDF_PARSE_MEMORY_BYTES = 512 * 1024 * 1024
PDF_PARSE_TIMEOUT_SECONDS = 15.0
PDF_HEADER = b"%PDF-"

GITHUB_PATTERN = re.compile(
    r"https?://(?:www\.)?github\s*\.\s*com\s*/\s*"
    r"(?P<owner>[A-Za-z0-9_.-]+)\s*/\s*"
    r"(?P<repo>[A-Za-z0-9_]+(?:[.-](?:[ \t]*\r?\n[ \t]*)?"
    r"[A-Za-z0-9_]+)*)",
    re.IGNORECASE,
)

class PdfRepositorySearcher:
    """从论文 PDF 中发现 GitHub 仓库，并读取仓库元数据。"""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        max_bytes: int = MAX_PDF_BYTES,
        timeout_seconds: float = 30.0,
        parse_timeout_seconds: float = PDF_PARSE_TIMEOUT_SECONDS,
        max_pages: int = MAX_PDF_PAGES,
        max_memory_bytes: int = MAX_PDF_PARSE_MEMORY_BYTES,
    ) -> None:
        """保存用于读取 GitHub 元数据的客户端。"""
        if (
            max_bytes <= 0
            or timeout_seconds <= 0
            or parse_timeout_seconds <= 0
            or max_pages <= 0
            or max_memory_bytes <= 0
        ):
            raise ValueError("PDF download limits must be positive")
        self.client = client
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds
        self.parse_timeout_seconds = parse_timeout_seconds
        self.max_pages = max_pages
        self.max_memory_bytes = max_memory_bytes
    
    async def search_github_links(
        self,
        paper: CodePaperInput,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """搜索代码仓库。"""

        if not 1 <= limit <= 100:
            raise ValueError(
                "PDF repository search limit must be between 1 and 100"
            )

        url = paper.pdf_url
        if url is None:
            return []
        
        pdf_bytes = await download(
            url,
            max_bytes=self.max_bytes,
            timeout_seconds=self.timeout_seconds,
        )
        
        github_links = await extract_pdf_links(
            pdf_bytes,
            timeout_seconds=self.parse_timeout_seconds,
            max_pages=self.max_pages,
            max_links=limit,
            max_memory_bytes=self.max_memory_bytes,
        )
        github_links_limit = github_links[:limit]
        
        repositories: list[dict[str, Any]] = []

        if not github_links_limit:
            return []
        
        for link in github_links_limit:
            repo = await get_github_repository(self.client, link)
            if repo is None:
                continue
            
            repositories.append(repo)
        
        
            
        return repositories



async def download(
    url: str,
    *,
    max_bytes: int = MAX_PDF_BYTES,
    timeout_seconds: float = 30.0,
    client: httpx.AsyncClient | None = None,
) -> bytes:
    """校验地址并在大小限制内流式下载 PDF。"""
    if max_bytes <= 0 or timeout_seconds <= 0:
        raise ValueError("PDF download limits must be positive")

    if client is not None:
        return await _download_with_client(
            client,
            url,
            max_bytes=max_bytes,
            require_pdf_header=True,
        )

    async with httpx.AsyncClient(
        timeout=timeout_seconds,
        follow_redirects=False,
        headers={"User-Agent": "module-agent/1.0"},
    ) as owned_client:
        return await _download_with_client(
            owned_client,
            url,
            max_bytes=max_bytes,
            require_pdf_header=True,
        )


async def download_text(
    url: str,
    *,
    max_bytes: int = MAX_TEXT_BYTES,
    timeout_seconds: float = 15.0,
) -> str:
    """安全下载有大小限制的论文落地页文本。"""
    if max_bytes <= 0 or timeout_seconds <= 0:
        raise ValueError("Document download limits must be positive")
    async with httpx.AsyncClient(
        timeout=timeout_seconds,
        follow_redirects=False,
        headers={"User-Agent": "module-agent/1.0"},
    ) as client:
        content = await _download_with_client(
            client,
            url,
            max_bytes=max_bytes,
            require_pdf_header=False,
        )
    return content.decode("utf-8", errors="replace")


async def _download_with_client(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int,
    require_pdf_header: bool,
) -> bytes:
    """下载 PDF，并逐跳检查重定向目标。"""
    current_url = url

    for redirect_count in range(MAX_REDIRECTS + 1):
        await _validate_public_http_url(current_url)

        async with client.stream(
            "GET",
            current_url,
            follow_redirects=False,
        ) as response:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise PdfDownloadError(
                        "PDF response redirects without a Location header"
                    )
                if redirect_count >= MAX_REDIRECTS:
                    raise PdfDownloadError(
                        f"PDF response exceeded {MAX_REDIRECTS} redirects"
                    )
                current_url = urljoin(str(response.url), location)
                continue

            response.raise_for_status()
            _reject_large_content_length(response, max_bytes=max_bytes)

            chunks: list[bytes] = []
            downloaded = 0
            async for chunk in response.aiter_bytes():
                downloaded += len(chunk)
                if downloaded > max_bytes:
                    raise PdfTooLargeError(
                        f"PDF exceeds the {max_bytes}-byte limit"
                    )
                chunks.append(chunk)

            content = b"".join(chunks)
            if require_pdf_header and PDF_HEADER not in content[:1024]:
                content_type = response.headers.get(
                    "content-type",
                    "unknown",
                ).split(";", 1)[0]
                raise InvalidPdfContentError(
                    "Downloaded content does not contain a PDF header "
                    f"(Content-Type: {content_type})"
                )
            return content

    raise PdfDownloadError("PDF redirect handling ended unexpectedly")


def _reject_large_content_length(
    response: httpx.Response,
    *,
    max_bytes: int,
) -> None:
    """根据 Content-Length 提前拒绝已知的超大响应。"""
    value = response.headers.get("content-length")
    if value is None:
        return
    try:
        content_length = int(value)
    except ValueError:
        return
    if content_length > max_bytes:
        raise PdfTooLargeError(
            f"PDF declares {content_length} bytes, above the "
            f"{max_bytes}-byte limit"
        )


async def _validate_public_http_url(url: str) -> None:
    """只允许解析到公网地址的 HTTP(S) URL。"""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafePdfUrlError("PDF URL must use HTTP or HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafePdfUrlError("PDF URL must not contain credentials")
    if parsed.hostname is None:
        raise UnsafePdfUrlError("PDF URL must contain a hostname")

    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except (socket.gaierror, UnicodeError) as exc:
        raise PdfDownloadError(
            f"Could not resolve PDF hostname: {parsed.hostname}"
        ) from exc

    if not addresses:
        raise PdfDownloadError(
            f"Could not resolve PDF hostname: {parsed.hostname}"
        )

    for _, _, _, _, sockaddr in addresses:
        host = sockaddr[0]

        if not isinstance(host, str):
            raise PdfDownloadError(
                f"Unexpected resolved PDF address: {sockaddr}"
            )

        host = host.split("%", 1)[0]

        try:
            ip = ipaddress.ip_address(host)
        except ValueError as exc:
            raise PdfDownloadError(
                f"Could not validate resolved PDF address: {host}"
            ) from exc

        if not ip.is_global:
            raise UnsafePdfUrlError(
                f"PDF URL resolves to a non-public address: {ip}"
            )
                
        

async def extract_pdf_links(
    pdf_bytes: bytes,
    *,
    timeout_seconds: float = PDF_PARSE_TIMEOUT_SECONDS,
    max_pages: int = MAX_PDF_PAGES,
    max_links: int = MAX_PDF_LINKS,
    max_text_characters: int = MAX_PDF_TEXT_CHARACTERS,
    max_annotations: int = MAX_PDF_ANNOTATIONS,
    max_memory_bytes: int = MAX_PDF_PARSE_MEMORY_BYTES,
) -> list[str]:
    """Parse untrusted PDF bytes in a killable subprocess."""
    limits = (
        timeout_seconds,
        max_pages,
        max_links,
        max_text_characters,
        max_annotations,
        max_memory_bytes,
    )
    if any(value <= 0 for value in limits):
        raise ValueError("PDF parsing limits must be positive")

    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_extract_worker,
        args=(
            sender,
            pdf_bytes,
            max_pages,
            max_links,
            max_text_characters,
            max_annotations,
            max_memory_bytes,
            ceil(timeout_seconds),
        ),
        daemon=True,
    )
    process.start()
    sender.close()
    try:
        try:
            status, payload = await asyncio.wait_for(
                asyncio.to_thread(receiver.recv),
                timeout=timeout_seconds,
            )
        except TimeoutError as exc:
            raise PdfParseTimeoutError(
                f"PDF parsing exceeded {timeout_seconds:g} seconds"
            ) from exc
        except EOFError as exc:
            raise PdfParseError(
                "PDF parser process exited without returning a result"
            ) from exc
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
        await asyncio.to_thread(process.join, 1.0)
        if process.is_alive():
            process.kill()
            await asyncio.to_thread(process.join)

    if status == "ok":
        return list(payload)
    if status == "limit":
        raise PdfResourceLimitError(str(payload))
    raise PdfParseError(str(payload))


def _extract_worker(
    connection: Connection,
    pdf_bytes: bytes,
    max_pages: int,
    max_links: int,
    max_text_characters: int,
    max_annotations: int,
    max_memory_bytes: int,
    max_cpu_seconds: int,
) -> None:
    """Run PDF extraction inside an isolated child process."""
    try:
        _apply_parser_resource_limits(
            max_memory_bytes=max_memory_bytes,
            max_cpu_seconds=max_cpu_seconds,
        )
        links = extract(
            pdf_bytes,
            max_pages=max_pages,
            max_links=max_links,
            max_text_characters=max_text_characters,
            max_annotations=max_annotations,
        )
        connection.send(("ok", links))
    except PdfResourceLimitError as exc:
        connection.send(("limit", str(exc)))
    # The process boundary must serialize every parser failure to its parent.
    except Exception as exc:  # noqa: BLE001
        connection.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        with suppress(Exception):
            connection.close()


def _apply_parser_resource_limits(
    *,
    max_memory_bytes: int,
    max_cpu_seconds: int,
) -> None:
    """Apply process limits when the resource module is available."""
    try:
        import resource
    except ImportError:
        return
    resource.setrlimit(
        resource.RLIMIT_AS,
        (max_memory_bytes, max_memory_bytes),
    )
    resource.setrlimit(
        resource.RLIMIT_CPU,
        (max_cpu_seconds, max_cpu_seconds + 1),
    )


def extract(
    pdf_bytes: bytes,
    *,
    max_pages: int = MAX_PDF_PAGES,
    max_links: int = MAX_PDF_LINKS,
    max_text_characters: int = MAX_PDF_TEXT_CHARACTERS,
    max_annotations: int = MAX_PDF_ANNOTATIONS,
) -> list[str]:
    """从PDF文件中提取GitHub链接。"""
    pdf_file = BytesIO(pdf_bytes)
    reader = PdfReader(pdf_file)

    page_count = len(reader.pages)
    if page_count > max_pages:
        raise PdfResourceLimitError(
            f"PDF has {page_count} pages, above the {max_pages}-page limit"
        )

    links: set[str] = set()
    text_characters = 0
    annotation_count = 0

    for page in reader.pages:
        # 1. 正文里的 URL
        text = page.extract_text() or ""
        text_characters += len(text)
        if text_characters > max_text_characters:
            raise PdfResourceLimitError(
                "PDF extracted text exceeds the configured character limit"
            )
        links.update(extract_github_links(text))
        if len(links) >= max_links:
            return sorted(links)[:max_links]

        # 2. PDF hyperlink annotation
        annotations = page.get("/Annots")

        if annotations is None:
            continue

        for annotation_ref in annotations:
            annotation_count += 1
            if annotation_count > max_annotations:
                raise PdfResourceLimitError(
                    "PDF annotations exceed the configured limit"
                )
            annotation = annotation_ref.get_object()

            action = annotation.get("/A")
            if action is None:
                continue

            uri = action.get("/URI")
            if not isinstance(uri, str):
                continue

            links.update(extract_github_links(uri))
            if len(links) >= max_links:
                return sorted(links)[:max_links]

    return sorted(links)[:max_links]


def extract_github_links(text: str) -> list[str]:
    """从普通文本或带换行的 PDF 文本中规范化 GitHub 仓库地址。"""
    links: set[str] = set()
    for match in GITHUB_PATTERN.finditer(text):
        owner = re.sub(r"\s+", "", match.group("owner"))
        repo = re.sub(r"\s+", "", match.group("repo"))
        if repo.casefold().endswith(".git"):
            repo = repo[:-4]
        if owner and repo:
            links.add(f"https://github.com/{owner}/{repo}")
    return sorted(links)


def parse_github_repo_url(url: str) -> tuple[str, str] | None:
    """解析 GitHub 仓库 URL。"""
    parsed = urlparse(url)
    if parsed.hostname not in {"github.com", "www.github.com"}:
        return None
    
    parts = [part for part in parsed.path.split("/") if part]
    
    if len(parts) < 2:
        return None
    
    owner = parts[0]
    repo = parts[1]
    if repo.casefold().endswith(".git"):
        repo = repo[:-4]
    
    return owner, repo

async def get_github_repository(
    client: httpx.AsyncClient,
    url: str,
) -> dict[str, Any] | None:
    """获取 GitHub 仓库信息。"""
    parse = parse_github_repo_url(url)
    
    if parse is None:
        return None
    
    owner, repo = parse
    
    response = await client.get(
        f"/repos/{owner}/{repo}",
    )

    if response.status_code == 404:
        return None

    response.raise_for_status()

    return response.json()
    
    
    
