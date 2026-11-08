"""GitHub 地址规范化及论文自身实现声明的保守识别，不访问网络。"""

import re
from urllib.parse import urlparse


GITHUB_PATTERN = re.compile(
    r"https?://(?:www\.)?github\s*\.\s*com\s*/\s*"
    r"(?P<owner>[A-Za-z0-9_.-]+)\s*/\s*"
    r"(?P<repo>[A-Za-z0-9_]+(?:[.-](?:[ \t]*\r?\n[ \t]*)?"
    r"[A-Za-z0-9_]+)*)",
    re.IGNORECASE,
)
_CODE_DECLARATION = re.compile(
    r"\b(?:our|the)\s+(?:source\s+)?(?:codes?|implementation|repository)\b"
    r"|\b(?:source\s+codes?|codes?|implementation)\s+(?:is|are|can\s+be|has\s+been)"
    r"\s+(?:\w+\s+){0,3}(?:available|released|found|accessed|provided)\b"
    r"|^\s*(?:source\s+code|code|implementation)\s*:"
    r"|(?:我们|本文|本研究)[^。；\n]{0,40}(?:代码|源码|实现)"
    r"|^\s*(?:代码|源码|实现)(?:地址)?\s*[:：]",
    re.IGNORECASE,
)
_REFERENCE_CONTEXT = re.compile(
    r"\b(?:baseline|benchmark|dataset|previous|prior|existing|third.party|related|not|never|unavailable)\b"
    r"|基准|数据集|已有|参考|引用|第三方|未公开|不提供",
    re.IGNORECASE,
)


def parse_repository_url(url: str) -> tuple[str, str] | None:
    """只接受真正指向 GitHub 仓库的 HTTP(S) 地址，不匹配查询参数中的地址。"""
    try:
        parsed = urlparse(url)
        if (
            parsed.scheme.casefold() not in {"http", "https"}
            or parsed.hostname not in {"github.com", "www.github.com"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 80, 443}
        ):
            return None
    except ValueError:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    owner, repository = parts[:2]
    if repository.casefold().endswith(".git"):
        repository = repository[:-4]
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]+", owner)
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", repository)
        or repository in {".", ".."}
        or owner.casefold()
        in {
            "orgs",
            "topics",
            "settings",
            "features",
            "marketplace",
            "collections",
            "sponsors",
        }
    ):
        return None
    return owner, repository


def repository_key(url: str) -> str | None:
    """忽略协议、大小写、.git 和子路径后比较仓库身份。"""
    parsed = parse_repository_url(url)
    return "/".join(parsed).casefold() if parsed else None


def _matched_url(match: re.Match[str]) -> str:
    owner = re.sub(r"\s+", "", match.group("owner"))
    repository = re.sub(r"\s+", "", match.group("repo"))
    if repository.casefold().endswith(".git"):
        repository = repository[:-4]
    return f"https://github.com/{owner}/{repository}"


def extract_repository_links(text: str) -> list[str]:
    """提取普通文本和 PDF 换行 URL，按仓库身份去重。"""
    links: dict[str, str] = {}
    for match in GITHUB_PATTERN.finditer(text):
        url = _matched_url(match)
        key = repository_key(url)
        if key:
            links.setdefault(key, url)
    return sorted(links.values())


def declared_implementation_links(text: str) -> list[str]:
    """只识别紧邻链接的自身代码声明；引用、基准链接不升级为实现声明。"""
    links: dict[str, str] = {}
    previous_end = 0
    for match in GITHUB_PATTERN.finditer(text):
        prefix = text[max(previous_end, match.start() - 240) : match.start()]
        # 上一个句子和上一个 URL 的声明不能传递给后面的引用链接。
        clause = re.split(r"(?<=[.!?;。；])\s+|\n\s*\n", prefix)[-1]
        previous_end = match.end()
        if not _CODE_DECLARATION.search(clause) or _REFERENCE_CONTEXT.search(clause):
            continue
        url = _matched_url(match)
        key = repository_key(url)
        if key:
            links.setdefault(key, url)
    return list(links.values())
