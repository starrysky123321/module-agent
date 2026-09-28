import asyncio
import ipaddress
import re
import socket
from io import BytesIO
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from pypdf import PdfReader

from module_agent.code.domain.errors import (
    InvalidPdfContentError,
    PdfDownloadError,
    PdfTooLargeError,
    UnsafePdfUrlError,
)
from module_agent.code.domain.request import CodePaperInput

MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
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
    ) -> None:
        """保存用于读取 GitHub 元数据的客户端。"""
        if max_bytes <= 0 or timeout_seconds <= 0:
            raise ValueError("PDF download limits must be positive")
        self.client = client
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds
    
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
        
        github_links = await asyncio.to_thread(extract, pdf_bytes)
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
                
        

def extract(pdf_bytes: bytes) -> list[str]:
    """从PDF文件中提取GitHub链接。"""
    pdf_file = BytesIO(pdf_bytes)
    reader = PdfReader(pdf_file)

    links: set[str] = set()

    for page in reader.pages:
        # 1. 正文里的 URL
        text = page.extract_text() or ""
        links.update(extract_github_links(text))

        # 2. PDF hyperlink annotation
        annotations = page.get("/Annots")

        if annotations is None:
            continue

        for annotation_ref in annotations:
            annotation = annotation_ref.get_object()

            action = annotation.get("/A")
            if action is None:
                continue

            uri = action.get("/URI")
            if not isinstance(uri, str):
                continue

            links.update(extract_github_links(uri))

    return sorted(links)


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
    
    
    
