"""pixiv 源测试：经 BaseSource 接口接缝，离线 mock 系统边界（HTTP transport / 时钟）。"""

import httpx
import pytest
from httpx import ASGITransport, AsyncClient, MockTransport

from comicfeed.infrastructure.database import create_tables, init_db
from comicfeed.infrastructure.source_manager import SourceManager
from comicfeed.sources.base import AuthSchema

_CLIENT_HASH = "68fa070e55d8ca52b0e989b6b91cc011"  # md5("1234567890" + HASH_SECRET)，独立于实现计算


def _auth_handler(request: httpx.Request) -> httpx.Response:
    """mock app-api：token 刷新 + 排行探活。断言请求头与请求体为外部可观察契约。"""
    if request.url.path == "/auth/token":
        assert request.headers["X-Client-Time"] == "1234567890"
        assert request.headers["X-Client-Hash"] == _CLIENT_HASH
        assert "refresh_token" in request.content.decode()
        return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600, "refresh_token": "rt-1"})
    if request.url.path == "/v1/illust/ranking":
        assert request.headers["Authorization"] == "Bearer at-1"
        return httpx.Response(200, json={"illusts": []})
    return httpx.Response(404)


def _make_source(handler, **kwargs):
    from comicfeed.sources.pixiv import PixivSource
    defaults = dict(
        credentials={"refresh_token": "rt-0"},
        transport=MockTransport(handler),
        time_fn=lambda: 1234567890.0,
    )
    defaults.update(kwargs)
    return PixivSource(**defaults)


async def test_pixiv_source_validates_as_plugin():
    """pixiv 源满足源插件校验：key/name/version/domains/auth_schema。"""
    from comicfeed.sources.pixiv import PixivSource
    manager = SourceManager()
    assert manager.validate_source(PixivSource) is True
    source = PixivSource()
    assert source.key == "pixiv"
    assert source.name == "Pixiv"
    assert source.version
    assert source.domains == ["app-api.pixiv.net"]
    assert source.auth_schema is AuthSchema.TOKEN


async def test_config_schema_encrypted_refresh_token_with_r18_hint():
    """配置 schema 暴露 refresh_token（加密）与 R-18 账号设置说明。"""
    from comicfeed.sources.pixiv import PixivSource
    schema = PixivSource().get_config_schema()
    by_key = {f["key"]: f for f in schema}
    assert "refresh_token" in by_key
    assert by_key["refresh_token"]["credential"] is True
    assert by_key["refresh_token"]["type"] == "password"
    assert "R-18" in by_key["refresh_token"].get("hint", "")


async def test_valid_refresh_token_connects():
    """有效 refresh_token：刷新成功并探活 app-api。"""
    source = _make_source(_auth_handler)
    ok, message = await source.test_connection()
    assert ok is True
    assert message == "连接成功"


async def test_token_reused_within_expiry():
    """access_token 有效期内复用，不重复请求 token 端点。"""
    auth_calls = 0

    def counting(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls
        if request.url.path == "/auth/token":
            auth_calls += 1
        return _auth_handler(request)

    source = _make_source(counting)
    await source.test_connection()
    await source.test_connection()
    assert auth_calls == 1


async def test_invalid_refresh_token_reports_failure():
    """无效 refresh_token：明确报错而非异常外泄。"""
    def reject(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(400, json={"has_error": True, "errors": {"system": {}}})
        return httpx.Response(404)

    source = _make_source(reject)
    ok, message = await source.test_connection()
    assert ok is False
    assert "refresh_token" in message


# --- Web 端点：/api/sources/{key}/test ---

@pytest.fixture
def app():
    init_db(":memory:")
    return _create_app()


def _create_app():
    from comicfeed.web.app import create_app
    return create_app({"auth_username": "admin", "auth_password": "secret"})


class _OkSource:
    async def test_connection(self):
        return True, "连接成功"


class _OkManager:
    def get_source_cls(self, key):
        return key if key == "pixiv" else None

    def get_source(self, key, credentials=None, proxy=None):
        assert credentials == {} and proxy is None
        return _OkSource()


async def test_test_connection_endpoint(app, monkeypatch):
    """测试连接端点返回源的探活结果；未知源 404。"""
    await create_tables()
    monkeypatch.setattr("comicfeed.web.routes.sources._get_manager", lambda: _OkManager())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/sources/pixiv/test", auth=("admin", "secret"))
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "message": "连接成功"}
        resp2 = await client.post("/api/sources/nope/test", auth=("admin", "secret"))
        assert resp2.status_code == 404
