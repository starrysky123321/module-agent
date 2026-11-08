"""Serve the local research workbench alongside the existing HTTP API."""

from pathlib import Path
from hashlib import sha256

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope


ASSETS_DIRECTORY = Path(__file__).with_name("workbench_assets")


class WorkbenchStaticFiles(StaticFiles):
    """Revalidate assets, including 304 responses, instead of heuristic caching."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


def is_workbench_public_path(path: str) -> bool:
    """Allow loading the interface before the user supplies an API token."""
    return path in {"/", "/ui/config"} or path.startswith("/ui/assets/")


def register_workbench(application: FastAPI, *, api_prefix: str) -> None:
    """Mount packaged assets and expose only public client configuration."""
    # A content revision keeps HTML, CSS and relative ES-module imports in the
    # same release, even when a browser still has the previous URLs cached.
    files = ("index.html", "workbench.css", "app.mjs", "core.mjs", "locale-zh.mjs", "experiments.mjs")
    revision = sha256(b"".join((ASSETS_DIRECTORY / name).read_bytes() for name in files)).hexdigest()[:16]
    asset_prefix = f"/ui/assets/{revision}"
    document = (ASSETS_DIRECTORY / "index.html").read_text(encoding="utf-8").replace(
        "/ui/assets/", f"{asset_prefix}/"
    )

    @application.get("/", include_in_schema=False)
    async def workbench() -> HTMLResponse:
        return HTMLResponse(
            document,
            headers={
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": (
                    "default-src 'self'; script-src 'self'; "
                    "style-src 'self'; img-src 'self' data:; "
                    "connect-src 'self'; object-src 'none'; "
                    "base-uri 'none'; frame-ancestors 'none'; "
                    "form-action 'self'"
                ),
            },
        )

    @application.get("/ui/config", include_in_schema=False)
    async def workbench_config() -> dict[str, str]:
        return {"api_prefix": api_prefix}

    application.mount(
        asset_prefix,
        WorkbenchStaticFiles(directory=ASSETS_DIRECTORY),
        name="workbench-versioned-assets",
    )
    # Keep existing asset URLs working for integrations and older bookmarks.
    application.mount(
        "/ui/assets",
        WorkbenchStaticFiles(directory=ASSETS_DIRECTORY),
        name="workbench-assets",
    )
