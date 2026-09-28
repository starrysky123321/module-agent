from __future__ import annotations

import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass

import pdfplumber
from curl_cffi import requests

from module_agent.venue_catalog.domain.models import VenueType


CCF_EDITION_YEAR = 2026
CCF_SOURCE_PAGE_URL = "https://www.ccf.org.cn/Academic_Evaluation/By_category/"
CCF_CATALOG_PDF_URL = (
    "https://www.ccf.org.cn/ccf/contentcore/resource/download?"
    "ID=112CF3BF7E1140ACEB271ADAED12A67ADFABB8FF099E40C2759502A85C8A281F"
)
CCF_CATALOG_SHA256 = "271b630b576bf8a4f802e767f5694caded93680e22b3a19bef7902591c45c1d3"

CCF_CATEGORIES = (
    "计算机体系结构/并行与分布计算/存储系统",
    "计算机网络",
    "网络与信息安全",
    "软件工程/系统软件/程序设计语言",
    "数据库/数据挖掘/内容检索",
    "计算机科学理论",
    "计算机图形学与多媒体",
    "人工智能",
    "人机交互与普适计算",
    "交叉/综合/新兴",
)

EXPECTED_RECORD_COUNT = 681
EXPECTED_TYPE_COUNTS = Counter(
    {VenueType.JOURNAL: 295, VenueType.CONFERENCE: 386}
)
EXPECTED_LEVEL_COUNTS = Counter({"A": 95, "B": 245, "C": 341})


@dataclass(frozen=True, slots=True)
class CCFVenueRecord:
    """封装 CCFVenueRecord 相关的数据和行为。"""
    # 会议或期刊标准名称。
    canonical_name: str
    # 可用于匹配的别名。
    aliases: tuple[str, ...]
    # 会议或期刊类型。
    venue_type: VenueType
    # 评级或严重程度。
    level: str
    # 评级所属研究领域。
    category: str
    # 评级版本年份。
    edition_year: int = CCF_EDITION_YEAR
    # 评级数据来源页面。
    source_url: str = CCF_SOURCE_PAGE_URL


def normalize_name(value: str) -> str:
    """规范化输入数据。"""
    return " ".join(value.casefold().split())


def _clean_display_name(value: str) -> str:
    return " ".join(value.replace("\n", " ").split())


def _split_current_and_former(value: str) -> tuple[str, str | None]:
    match = re.search(r"（原\s*(.*?)）", value, flags=re.DOTALL)
    current = value[: match.start()] if match else value
    former = match.group(1) if match else None
    return _clean_display_name(current), (
        _clean_display_name(former) if former else None
    )


def _extract_aliases(acronym: str, full_name: str) -> tuple[str, ...]:
    current_acronym, former_acronym = _split_current_and_former(acronym)
    _, former_full_name = _split_current_and_former(full_name)

    aliases: list[str] = []
    compact_acronym = re.sub(r"\s*\n\s*", "", acronym.split("（原", 1)[0]).strip()
    for alias in (compact_acronym, current_acronym, former_acronym, former_full_name):
        if not alias:
            continue
        cleaned = _clean_display_name(alias)
        if cleaned and normalize_name(cleaned) not in {
            normalize_name(existing) for existing in aliases
        }:
            aliases.append(cleaned)
    return tuple(aliases)


def download_ccf_catalog() -> bytes:
    """下载并解析 CCF 评级目录。"""
    response = requests.get(
        CCF_CATALOG_PDF_URL,
        impersonate="chrome",
        timeout=60,
    )
    response.raise_for_status()
    content = response.content

    if not content.startswith(b"%PDF"):
        raise ValueError("CCF catalog download did not return a PDF")

    digest = hashlib.sha256(content).hexdigest()
    if digest != CCF_CATALOG_SHA256:
        raise ValueError(
            "CCF catalog PDF changed; verify the new official edition before importing "
            f"(sha256={digest})"
        )
    return content


def parse_ccf_catalog(pdf_content: bytes) -> list[CCFVenueRecord]:
    """解析输入并返回结构化结果。"""
    records: list[CCFVenueRecord] = []
    current_category: str | None = None
    current_level: str | None = None
    current_venue_type: VenueType | None = None

    with pdfplumber.open(io.BytesIO(pdf_content)) as catalog:
        for page in catalog.pages:
            page_text = page.extract_text() or ""
            compact_page_text = "".join(page_text.split())

            for category in CCF_CATEGORIES:
                if "".join(category.split()) in compact_page_text:
                    current_category = category
                    break

            level_matches = re.findall(r"[一二三]、\s*([ABC])\s*类", page_text)
            if level_matches:
                current_level = level_matches[-1]

            tables = page.extract_tables(
                {"text_x_tolerance": 1, "text_y_tolerance": 3}
            )
            for table in tables:
                if not table or not table[0]:
                    continue

                header = " ".join(cell or "" for cell in table[0])
                rows = table[1:]
                if "期刊简称" in header:
                    current_venue_type = VenueType.JOURNAL
                elif "会议简称" in header:
                    current_venue_type = VenueType.CONFERENCE
                elif _is_data_row(table[0]):
                    rows = table
                else:
                    continue

                if current_category is None or current_level is None:
                    raise ValueError("CCF catalog table is missing category or level context")
                if current_venue_type is None:
                    raise ValueError("CCF catalog table is missing venue type context")

                for row in rows:
                    if not _is_data_row(row) or len(row) < 3:
                        continue

                    acronym = row[1] or ""
                    full_name = row[2] or ""
                    canonical_name, _ = _split_current_and_former(full_name)
                    if not canonical_name:
                        raise ValueError("CCF catalog contains an empty venue name")

                    aliases = tuple(
                        alias
                        for alias in _extract_aliases(acronym, full_name)
                        if normalize_name(alias) != normalize_name(canonical_name)
                    )
                    records.append(
                        CCFVenueRecord(
                            canonical_name=canonical_name,
                            aliases=aliases,
                            venue_type=current_venue_type,
                            level=current_level,
                            category=current_category,
                        )
                    )

    _validate_catalog(records)
    return records


def _is_data_row(row: list[str | None]) -> bool:
    return bool(row) and " ".join((row[0] or "").split()).isdigit()


def _validate_catalog(records: list[CCFVenueRecord]) -> None:
    if len(records) != EXPECTED_RECORD_COUNT:
        raise ValueError(
            f"Expected {EXPECTED_RECORD_COUNT} CCF records, parsed {len(records)}"
        )

    type_counts = Counter(record.venue_type for record in records)
    if type_counts != EXPECTED_TYPE_COUNTS:
        raise ValueError(f"Unexpected CCF venue type counts: {type_counts}")

    level_counts = Counter(record.level for record in records)
    if level_counts != EXPECTED_LEVEL_COUNTS:
        raise ValueError(f"Unexpected CCF level counts: {level_counts}")
