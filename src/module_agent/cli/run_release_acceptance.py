"""Command-line entry point for the release acceptance workflow."""

import argparse
import asyncio
from datetime import date
import os
from pathlib import Path

from module_agent.cli.release_acceptance import (
    AcceptanceConfig,
    AcceptanceStage,
    AcceptanceStageResult,
    ReleaseAcceptanceReport,
    ReleaseAcceptanceRunner,
    run_release_acceptance,
)
from module_agent.literature.domain.search import SearchRequest


__all__ = [
    "AcceptanceConfig",
    "AcceptanceStage",
    "AcceptanceStageResult",
    "ReleaseAcceptanceReport",
    "ReleaseAcceptanceRunner",
    "run_release_acceptance",
]


def _read_api_token() -> str:
    direct = os.getenv("API_AUTH_TOKEN", "").strip()
    secret_file = os.getenv("API_AUTH_TOKEN_FILE", "").strip()
    if direct and secret_file:
        raise ValueError(
            "configure only API_AUTH_TOKEN or API_AUTH_TOKEN_FILE"
        )
    if secret_file:
        value = Path(secret_file).read_text(encoding="utf-8").strip()
        if not value:
            raise ValueError("API_AUTH_TOKEN_FILE cannot be empty")
        return value
    return direct


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "date must use YYYY-MM-DD format"
        ) from exc


def _parse_args() -> AcceptanceConfig:
    today = date.today()
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--description")
    parser.add_argument(
        "--start-date",
        type=_parse_date,
        default=date(today.year - 3, 1, 1),
    )
    parser.add_argument("--end-date", type=_parse_date, default=today)
    parser.add_argument("--keyword", action="append", dest="keywords")
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--paper-count", type=int, default=1)
    parser.add_argument("--code-requirements")
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()
    search_request = SearchRequest(
        topic=args.topic,
        description=(
            args.description or f"Release acceptance for {args.topic}"
        ),
        start_date=args.start_date,
        end_date=args.end_date,
        keywords=args.keywords or [args.topic],
        max_results=args.max_results,
    )
    return AcceptanceConfig(
        base_url=args.base_url,
        search_request=search_request,
        paper_count=args.paper_count,
        code_requirements=args.code_requirements,
        poll_interval_seconds=args.poll_interval_seconds,
        timeout_seconds=args.timeout_seconds,
    )


def main() -> None:
    report = asyncio.run(
        run_release_acceptance(_parse_args(), token=_read_api_token())
    )
    print(report.model_dump_json(indent=2))
    if not report.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
