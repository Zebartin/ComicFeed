from comicfeed.database import create_tables, get_session, init_db
from comicfeed.models import Gallery


async def test_delete_gallery():
    """删除画廊只删 DB 记录。"""
    init_db(":memory:")
    await create_tables()

    async with get_session() as session:
        session.add(Gallery(id="nhentai:1", source_key="nhentai", native_id="1",
                    normalized_title="test"))
        await session.commit()

    from httpx import ASGITransport, AsyncClient
    from comicfeed.web.app import create_app
    app = create_app({"auth_username": "a", "auth_password": "b"})
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.delete("/api/galleries/nhentai:1", auth=("a", "b"))
        assert r.status_code == 204

    async with get_session() as session:
        g = await session.get(Gallery, "nhentai:1")
        assert g is None
