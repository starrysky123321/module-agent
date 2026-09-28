"""Prometheus scrape endpoint."""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest


metrics_router = APIRouter(tags=["observability"])


@metrics_router.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    """Expose metrics in the Prometheus text format."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
