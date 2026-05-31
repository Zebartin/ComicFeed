from sqlalchemy import select

from comicfeed.infrastructure.database import create_tables, get_session, init_db
from comicfeed.models import Gallery, Subscription, SubscriptionGallery


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


async def test_gallery_subscription_nm_relation():
    """一个 Gallery 可以关联到多个 Subscription。"""
    init_db(":memory:")
    await create_tables()

    async with get_session() as session:
        sub1 = Subscription(name="A", source_key="nhentai", query="a", mode="SEARCH")
        sub2 = Subscription(name="B", source_key="nhentai", query="b", mode="SEARCH")
        session.add_all([sub1, sub2])
        await session.flush()

        gallery = Gallery(
            id="nhentai:455819",
            source_key="nhentai",
            native_id="455819",
            normalized_title="sample comic",
            reported_pages=32,
        )
        session.add(gallery)
        await session.flush()

        session.add(SubscriptionGallery(subscription_id=sub1.id, gallery_id=gallery.id))
        session.add(SubscriptionGallery(subscription_id=sub2.id, gallery_id=gallery.id))
        await session.commit()

    async with get_session() as session:
        g = await session.get(Gallery, "nhentai:455819")
        assert len(g.subscriptions) == 2
        assert {sg.subscription_id for sg in g.subscriptions} == {sub1.id, sub2.id}
