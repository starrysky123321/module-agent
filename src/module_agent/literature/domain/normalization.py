import unicodedata, re

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
