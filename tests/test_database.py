from comicfeed.infrastructure.database import create_tables, init_db, get_session
from comicfeed.models import Source


async def test_create_and_query_source():
    """可以创建数据库表，插入一个 Source 并查询出来。"""
    init_db(":memory:")
    await create_tables()

    async with get_session() as session:
        source = Source(key="nhentai", name="nHentai", enabled=True)
        session.add(source)
        await session.commit()

    async with get_session() as session:
        result = await session.get(Source, "nhentai")
        assert result is not None
        assert result.key == "nhentai"
        assert result.name == "nHentai"
        assert result.enabled is True
