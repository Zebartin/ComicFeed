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
