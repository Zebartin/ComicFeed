import pytest
from httpx import ASGITransport, AsyncClient

from comicfeed.database import create_tables, init_db, get_session
from comicfeed.web.app import create_app


@pytest.fixture
def app():
    init_db(":memory:")
    # tables created on app startup — create them here for tests
    return create_app({"auth_username": "admin", "auth_password": "secret"})


@pytest.fixture
async def db_tables():
    await create_tables()
    yield
    # cleanup not needed for :memory:


@pytest.fixture
def transport(app):
    return ASGITransport(app=app)


@pytest.fixture
def auth():
    return ("admin", "secret")


# --- Auth tests ---

async def test_health_endpoint_no_auth(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


async def test_protected_route_requires_auth(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/subscriptions")
        assert resp.status_code == 401


# --- Subscription CRUD ---

async def test_create_subscription(transport, auth, db_tables):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/subscriptions",
            json={"name": "测试", "source_key": "nhentai", "query": "full_color", "mode": "SEARCH"},
            auth=auth,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "测试"
        assert data["source_key"] == "nhentai"
        assert data["id"] > 0


async def test_list_subscriptions(transport, auth, db_tables):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # create two
        await client.post("/api/subscriptions", json={"name": "A", "source_key": "nhentai", "query": "a", "mode": "SEARCH"}, auth=auth)
        await client.post("/api/subscriptions", json={"name": "B", "source_key": "nhentai", "query": "b", "mode": "SEARCH"}, auth=auth)
        # list
        resp = await client.get("/api/subscriptions", auth=auth)
        assert resp.status_code == 200
        assert len(resp.json()) == 2


async def test_update_subscription(transport, auth, db_tables):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/subscriptions", json={"name": "Old", "source_key": "nhentai", "query": "x", "mode": "SEARCH"}, auth=auth)
        sub_id = r.json()["id"]
        r2 = await client.put(f"/api/subscriptions/{sub_id}", json={"name": "New", "enabled": False}, auth=auth)
        assert r2.status_code == 200
        assert r2.json()["name"] == "New"
        assert r2.json()["enabled"] is False


async def test_delete_subscription(transport, auth, db_tables):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/subscriptions", json={"name": "Del", "source_key": "nhentai", "query": "x", "mode": "SEARCH"}, auth=auth)
        sub_id = r.json()["id"]
        r2 = await client.delete(f"/api/subscriptions/{sub_id}", auth=auth)
        assert r2.status_code == 204
        r3 = await client.get("/api/subscriptions", auth=auth)
        assert len(r3.json()) == 0
