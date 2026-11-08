import unicodedata, re
from urllib.parse import unquote, urlparse


def normalize_doi(doi: str | None) -> str | None:
    """规范化输入数据。"""
    if not doi:
        return None

    normalized = doi.strip()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
    ):
        if normalized.lower().startswith(prefix):
            return normalized[len(prefix) :]
    return normalized


def normalize_title(title: str) -> str:
    """规范化输入数据。"""
    normalized = unicodedata.normalize("NFKC", title).casefold()

    normalized = re.sub(r"[\W_]+", " ", normalized)

    normalized = " ".join(normalized.split())

    return normalized


def normalize_arxiv_id(value: str | None) -> str | None:
    """从 arXiv DOI、正文/PDF URL 或标识中提取不带版本号的编号。"""
    if not value:
        return None
    identifier = unquote(value.strip()).casefold()
    doi = normalize_doi(identifier) or ""
    if doi.startswith("10.48550/arxiv."):
        identifier = doi.removeprefix("10.48550/arxiv.")
    elif "://" in identifier:
        parsed = urlparse(identifier)
        if parsed.hostname not in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
            return None
        path = parsed.path.lstrip("/")
        if not path.startswith(("abs/", "pdf/", "html/")):
            return None
        identifier = path.split("/", 1)[1].removesuffix(".pdf")
    else:
        identifier = identifier.removeprefix("arxiv:")
    match = re.fullmatch(r"(\d{4}\.\d{4,5}|[a-z][a-z.\-]+/\d{7})(?:v\d+)?", identifier)
    return match.group(1) if match else None
