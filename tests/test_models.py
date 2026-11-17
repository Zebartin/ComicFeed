from sqlalchemy import select
import pytest

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


@pytest.mark.parametrize("migration_fails", [False, True])
async def test_existing_database_accepts_unknown_favorites_and_keeps_gallery_pages(
    tmp_path, migration_fails
):
    from sqlalchemy import MetaData, create_engine, event
    from comicfeed.models import Base
    from comicfeed.repositories.gallery import get_or_create
    from comicfeed.repositories.page import ids_for_gallery

    path = tmp_path / "legacy.db"
    legacy = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(legacy)
    legacy.tables["gallery"].c.num_favorites.nullable = False
    engine = create_engine(f"sqlite:///{path}")
    legacy.create_all(engine)
    with engine.begin() as conn:
        conn.execute(legacy.tables["gallery"].insert().values(
            id="nhentai:7", source_key="nhentai", native_id="7",
            normalized_title="Existing gallery", num_favorites=321,
            reported_pages=1, actual_pages=1,
        ))
        conn.execute(legacy.tables["page"].insert().values(
            gallery_id="nhentai:7", page_native_id="original-page",
        ))
    engine.dispose()

    init_db(str(path))
    if migration_fails:
        async with get_session() as session:
            migration_engine = session.bind.sync_engine

        def fail_before_rename(conn, cursor, statement, parameters, context, executemany):
            if statement == "ALTER TABLE _gallery_nullable RENAME TO gallery":
                raise RuntimeError("simulated migration failure")

        event.listen(migration_engine, "before_cursor_execute", fail_before_rename)
        try:
            with pytest.raises(RuntimeError, match="simulated migration failure"):
                await create_tables()
        finally:
            event.remove(migration_engine, "before_cursor_execute", fail_before_rename)
    await create_tables()
    async with get_session() as session:
        await get_or_create(session, "4khd:42", "4khd", "42", "Sample", "", "",
                            [], None, 2, 2)
        await session.commit()
    await create_tables()  # 重复启动不会再次迁移或丢失已有数据。
    async with get_session() as session:
        from comicfeed.models import Gallery
        existing = await session.get(Gallery, "nhentai:7")
        new = await session.get(Gallery, "4khd:42")
        assert existing.num_favorites == 321
        assert existing.actual_pages == 1
        assert new.num_favorites is None
        assert await ids_for_gallery(session, "nhentai:7") == ["original-page"]
