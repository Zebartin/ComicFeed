import pytest
from datetime import datetime, timedelta

from comicfeed.infrastructure.database import create_tables, get_session, init_db
from comicfeed.models import DownloadEvent
from comicfeed.repositories.download_event import delete_before, pending_since, record_event


@pytest.fixture(autouse=True)
async def _db():
    init_db(":memory:")
    await create_tables()
    yield


async def test_record_and_pending_since():
    """记录事件后 pending_since 按时间升序返回。"""
    since = datetime.now() - timedelta(hours=1)
    async with get_session() as s:
        await record_event(s, subscription_id=1, subscription_name="订阅A",
                           source_key="nhentai", gallery_id="nhentai:123",
                           title="Title", page_count=10)
        await record_event(s, subscription_name="手动下载", source_key="exhentai",
                           gallery_id="exhentai:456", status="failed", error="boom")
        await s.commit()

    async with get_session() as s:
        events = await pending_since(s, since)
    assert len(events) == 2
    assert events[0].subscription_name == "订阅A"
    assert events[0].status == "success"
    assert events[0].gallery_id == "nhentai:123"
    assert events[1].subscription_name == "手动下载"
    assert events[1].status == "failed"
    assert events[1].error == "boom"


async def test_pending_since_excludes_old():
    """created_at 在 since 之前的事件不返回。"""
    old = datetime.now() - timedelta(days=2)
    async with get_session() as s:
        s.add(DownloadEvent(subscription_name="旧", source_key="nhentai",
                            gallery_id="g1", created_at=old))
        await s.commit()
    since = datetime.now() - timedelta(days=1)

    async with get_session() as s:
        events = await pending_since(s, since)
    assert events == []


async def test_delete_before():
    """删除 created_at <= cutoff 的事件。"""
    now = datetime.now()
    async with get_session() as s:
        for days, name in [(80, "old"), (20, "new")]:
            s.add(DownloadEvent(subscription_name=name, source_key="nhentai",
                                gallery_id=f"g-{days}", created_at=now - timedelta(days=days)))
        await s.commit()

    cutoff = now - timedelta(days=60)
    async with get_session() as s:
        deleted = await delete_before(s, cutoff)
        await s.commit()
    assert deleted == 1

    async with get_session() as s:
        remaining = [e.subscription_name for e in await pending_since(s, now - timedelta(days=90))]
    assert remaining == ["new"]


async def test_old_download_events_gain_warning_field_without_losing_records(tmp_path):
    from sqlalchemy import text

    path = str(tmp_path / "events.db")
    init_db(path)
    await create_tables()
    async with get_session() as session:
        await record_event(session, source_key="nhentai", gallery_id="nhentai:1", title="Existing")
        await session.commit()
        # 模拟上一版本没有 warning 列、已存有下载事件的数据库。
        await session.execute(text("ALTER TABLE download_event DROP COLUMN warning"))
        await session.commit()
    await create_tables()
    warning = "标注 3 张，公开 2 张"
    async with get_session() as session:
        await record_event(session, source_key="4khd", gallery_id="4khd:42",
                           title="Partial", page_count=2, warning=warning)
        await session.commit()
    init_db(path)
    await create_tables()
    async with get_session() as session:
        events = await pending_since(session, datetime(1970, 1, 1))
    assert [event.gallery_id for event in events] == ["nhentai:1", "4khd:42"]
    assert [event.warning for event in events] == ["", warning]
    assert all(event.status == "success" for event in events)
