"""The public interface must load without exposing authenticated API data."""

import asyncio
import re
import shutil

import httpx
import pytest
from fastapi import FastAPI

from module_agent.api.auth import register_api_auth_middleware
from module_agent.api.rate_limit import register_api_rate_limit_middleware
from module_agent.api.workbench import register_workbench
from module_agent.api import workbench as workbench_module
from module_agent.shared.config import AppSettings


class UnavailableRateLimitStore:
    async def eval(self, *args: object) -> object:
        raise AssertionError("Public workbench assets must not consume API quota")


def application() -> FastAPI:
    app = FastAPI()
    settings = AppSettings(
        _env_file=None,
        app_env="production",
        api_auth_token="workbench-test-token-that-is-long-enough",
        api_rate_limit_enabled=True,
    )
    register_workbench(app, api_prefix="/custom-api")
    register_api_rate_limit_middleware(app, settings, UnavailableRateLimitStore())
    register_api_auth_middleware(app, settings)

    @app.get("/custom-api/private")
    async def private() -> dict[str, str]:
        return {"status": "ok"}

    return app


def get(path: str, headers: dict[str, str] | None = None) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application()),
            base_url="http://test",
        ) as client:
            return await client.get(path, headers=headers)

    return asyncio.run(send())


def test_workbench_is_available_without_token_or_redis() -> None:
    response = get("/")

    assert response.status_code == 200
    assert 'lang="zh-CN"' in response.text
    assert re.search(r'/ui/assets/[a-f0-9]{16}/app\.mjs', response.text)
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-cache"


@pytest.mark.parametrize("asset", ["app.mjs", "core.mjs", "locale-zh.mjs", "workbench.css"])
def test_packaged_assets_are_public(asset: str) -> None:
    response = get(f"/ui/assets/{asset}")

    assert response.status_code == 200
    assert response.content
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("asset", ["app.mjs", "core.mjs", "locale-zh.mjs", "workbench.css"])
def test_versioned_assets_share_a_release_and_revalidate(asset: str) -> None:
    prefix = re.search(r'/ui/assets/[a-f0-9]{16}', get("/").text)
    assert prefix is not None
    response = get(f"{prefix.group()}/{asset}")

    assert response.status_code == 200
    assert response.content == get(f"/ui/assets/{asset}").content
    assert response.headers["Cache-Control"] == "no-cache"
    cached = get(f"{prefix.group()}/{asset}", {"If-None-Match": response.headers["ETag"]})
    assert cached.status_code == 304
    assert cached.headers["Cache-Control"] == "no-cache"


def test_asset_revision_changes_when_styles_change(tmp_path, monkeypatch) -> None:
    assets = tmp_path / "assets"
    shutil.copytree(workbench_module.ASSETS_DIRECTORY, assets)
    monkeypatch.setattr(workbench_module, "ASSETS_DIRECTORY", assets)
    before = get("/").text
    stylesheet = assets / "workbench.css"
    stylesheet.write_text(stylesheet.read_text() + "\n/* new UI release */\n")
    after = get("/").text

    assert re.search(r'/ui/assets/[a-f0-9]{16}', before).group() != re.search(r'/ui/assets/[a-f0-9]{16}', after).group()


def test_navigation_icons_have_intrinsic_bounds_without_styles() -> None:
    icons = re.findall(r'<svg class="nav-icon"[^>]+>', get("/").text)

    assert len(icons) == 4
    assert all('width="18"' in icon and 'height="18"' in icon for icon in icons)
    assert all('fill="none"' in icon and 'stroke="currentColor"' in icon for icon in icons)


def test_client_config_contains_only_api_prefix() -> None:
    response = get("/ui/config")

    assert response.status_code == 200
    assert response.json() == {"api_prefix": "/custom-api"}


@pytest.mark.parametrize("path", ["/custom-api/private", "/ui/private", "/ui/assets-malicious", "/ui/config/private"])
def test_public_interface_does_not_bypass_api_auth(path: str) -> None:
    response = get(path)

    assert response.status_code == 401


def test_static_mount_rejects_parent_directory_traversal() -> None:
    response = get("/ui/assets/%2e%2e/auth.py")

    assert response.status_code == 404
