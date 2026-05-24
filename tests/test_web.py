import pytest
from httpx import AsyncClient, ASGITransport

from comicfeed.web.app import create_app


@pytest.fixture
def app():
    return create_app({"auth_username": "admin", "auth_password": "secret"})


@pytest.fixture
def transport(app):
    return ASGITransport(app=app)


async def test_health_endpoint_no_auth(transport):
    """健康检查端点不需要认证。"""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


async def test_protected_route_requires_auth(transport):
    """受保护的 API 路由在无认证时返回 401。"""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/subscriptions")
        assert resp.status_code == 401


async def test_protected_route_with_valid_auth(transport):
    """正确的凭证可以访问受保护路由。"""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/subscriptions",
            auth=("admin", "secret"),
        )
        assert resp.status_code == 200


async def test_protected_route_with_invalid_auth(transport):
    """错误的凭证返回 401。"""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/subscriptions",
            auth=("admin", "wrong"),
        )
        assert resp.status_code == 401
