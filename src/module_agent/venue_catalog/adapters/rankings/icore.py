from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from time import sleep
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException

from module_agent.venue_catalog.domain.models import VenueType


ICORE_EDITION_YEAR = 2026
ICORE_RANKING_SYSTEM = "core"
ICORE_SOURCE_URL = (
    "https://portal.core.edu.au/conf-ranks/"
    "?by=all&page={page}&search=&sort=atitle&source=ICORE2026"
)
ICORE_EXPECTED_PAGE_COUNT = 20
ICORE_EXPECTED_RECORD_COUNT = 987
ICORE_EXPECTED_LEVEL_COUNTS = Counter(
    {
        "A*": 62,
        "A": 108,
        "B": 249,
        "Australasian B": 6,
        "C": 381,
        "Australasian C": 19,
    }
)


@dataclass(frozen=True, slots=True)
class ICOREVenueRecord:
    """封装 ICOREVenueRecord 相关的数据和行为。"""
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
    edition_year: int = ICORE_EDITION_YEAR
    # 评级数据来源页面。
    source_url: str = ICORE_SOURCE_URL.format(page=1)


def parse_icore_page(html: str) -> list[ICOREVenueRecord]:
    """解析输入并返回结构化结果。"""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        raise ValueError("ICORE page does not contain a rankings table")

    headers = [cell.get_text(" ", strip=True) for cell in table.find_all("th")]
    expected_headers = [
        "Title",
        "Acronym",
        "Source",
        "Rank",
        "Note",
        "DBLP",
        "Primary FoR",
        "Comments",
        "Average Rating",
    ]
    if headers != expected_headers:
        raise ValueError(f"Unexpected ICORE table headers: {headers}")

    records: list[ICOREVenueRecord] = []
    for row in table.find_all("tr")[1:]:
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
        if not cells:
            continue
        if len(cells) != len(expected_headers):
            raise ValueError(f"Unexpected ICORE row width: {len(cells)}")

        title, acronym, source, level, _, _, primary_for, _, _ = cells
        if source != "ICORE2026":
            raise ValueError(f"Unexpected ICORE source: {source}")
        if not title or not acronym or not level:
            raise ValueError("ICORE row is missing title, acronym, or rank")

        detail_path = _extract_detail_path(row.get("onclick"))
        records.append(
            ICOREVenueRecord(
                canonical_name=title,
                aliases=(acronym,),
                venue_type=VenueType.CONFERENCE,
                level=level,
                category=primary_for,
                source_url=urljoin("https://portal.core.edu.au", detail_path),
            )
        )
    return records


def download_icore_catalog() -> list[ICOREVenueRecord]:
    """下载并解析 ICORE 评级目录。"""
    with ThreadPoolExecutor(max_workers=5) as executor:
        pages = executor.map(_download_page, range(1, ICORE_EXPECTED_PAGE_COUNT + 1))
        records = [record for page in pages for record in page]

    _validate_catalog(records)
    return records


def _download_page(page: int) -> list[ICOREVenueRecord]:
    last_error: RequestException | None = None
    for attempt in range(3):
        try:
            response = requests.get(
                ICORE_SOURCE_URL.format(page=page),
                impersonate="chrome",
                timeout=60,
            )
            response.raise_for_status()
            return parse_icore_page(response.text)
        except RequestException as error:
            last_error = error
            if attempt < 2:
                sleep(attempt + 1)

    raise RuntimeError(f"Failed to download ICORE page {page}") from last_error


def _extract_detail_path(onclick: str | None) -> str:
    prefix = "navigate('"
    suffix = "')"
    if not onclick or not onclick.startswith(prefix) or not onclick.endswith(suffix):
        raise ValueError(f"Unexpected ICORE row navigation: {onclick!r}")
    return onclick[len(prefix) : -len(suffix)]


def _validate_catalog(records: list[ICOREVenueRecord]) -> None:
    if len(records) != ICORE_EXPECTED_RECORD_COUNT:
        raise ValueError(
            f"Expected {ICORE_EXPECTED_RECORD_COUNT} ICORE records, "
            f"parsed {len(records)}"
        )

    unique_records = {
        (record.canonical_name, record.aliases, record.edition_year)
        for record in records
    }
    if len(unique_records) != len(records):
        raise ValueError("ICORE catalog contains duplicate conference records")

    actual_counts = Counter(record.level for record in records)
    ranked_counts = Counter(
        {
            level: actual_counts[level]
            for level in ICORE_EXPECTED_LEVEL_COUNTS
        }
    )
    if ranked_counts != ICORE_EXPECTED_LEVEL_COUNTS:
        raise ValueError(f"Unexpected ICORE level counts: {ranked_counts}")
