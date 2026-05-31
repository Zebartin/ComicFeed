from sqlalchemy import select

from comicfeed.infrastructure.database import create_tables, get_session, init_db
from comicfeed.models import Subscription


async def test_create_and_query_subscription():
    """创建订阅并查询。"""
    init_db(":memory:")
    await create_tables()

    async with get_session() as session:
        sub = Subscription(
            name="测试订阅",
            source_key="nhentai",
            query="full_color",
            mode="SEARCH",
            interval_minutes=60,
            cbz_max_pages=30,
            enabled=True,
        )
        session.add(sub)
        await session.commit()

    async with get_session() as session:
        result = await session.get(Subscription, sub.id)
        assert result is not None
        assert result.name == "测试订阅"
        assert result.source_key == "nhentai"
        assert result.query == "full_color"
        assert result.mode == "SEARCH"
        assert result.interval_minutes == 60
        assert result.cbz_max_pages == 30
        assert result.enabled is True
