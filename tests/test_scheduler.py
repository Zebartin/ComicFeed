from comicfeed.infrastructure.database import create_tables, get_session, init_db
from comicfeed.models import Gallery, Subscription
from comicfeed.infrastructure.scheduler import check_subscription
from comicfeed.sources.base import AuthSchema, BaseSource, GallerySummary, SearchResult, UpdateResult


class _FakeSource(BaseSource):
    key = "fake"
    name = "Fake"
    version = "1.0"
    domains = ["fake.local"]
    auth_schema = AuthSchema.NONE
    search_results: list[GallerySummary] = []

    async def search(self, query, page, sort="date") -> SearchResult:
        return SearchResult(items=self.search_results, total_pages=1, current_page=1)

    async def get_gallery(self, gallery_id, gallery_url=""):
        raise NotImplementedError

    async def download_pages(self, gallery_id, page_range, gallery_url="", detail=None, on_page=None):
        raise NotImplementedError

    async def check_updates(self, gallery_id, last_known, gallery_url=""):
        return UpdateResult()


async def test_check_subscription_finds_new_galleries():
    """检查订阅返回 DB 中不存在的画廊摘要。"""
    init_db(":memory:")
    await create_tables()

    # 在 DB 中插入一个已下载的画廊
    async with get_session() as session:
        session.add(Gallery(
            id="fake:1", source_key="fake", native_id="1",
            normalized_title="existing",
        ))
        sub = Subscription(name="test", source_key="fake", query="test", mode="SEARCH")
        session.add(sub)
        await session.commit()
        sub_id = sub.id

    # 模拟搜索结果：一个已存在、一个新
    source = _FakeSource()
    source.search_results = [
        GallerySummary(native_id="1", title="Existing", cover_url="", page_count=10),
        GallerySummary(native_id="2", title="New One", cover_url="", page_count=20),
    ]

    async with get_session() as session:
        new, has_more = await check_subscription(session, sub_id, source)
        assert len(new) == 1
        assert new[0].native_id == "2"
        assert has_more is False


async def test_check_failure_records_failed_event(monkeypatch):
    """巡检中订阅检查抛错（如 Cookie 失效）→ 记录 failed 事件供摘要邮件 + 源错误通知。"""
    from comicfeed.repositories.download_event import pending_since
    from comicfeed.infrastructure.scheduler import run_all_checks
    from comicfeed.sources.exhentai import ExHentaiAuthError

    init_db(":memory:")
    await create_tables()
    async with get_session() as session:
        sub = Subscription(name="测试订阅", source_key="fake", query="x", mode="SEARCH", enabled=True)
        session.add(sub)
        await session.commit()
        sub_id = sub.id

    class _Mgr:
        def get_source(self, key, credentials=None, proxy=None):
            return object()

    async def _boom(session, subscription_id, source, max_search_pages=1):
        raise ExHentaiAuthError("Cookie 已失效：被重定向到 Sad Panda 页，请更新源 Cookie")

    notified = []

    async def _notify(data):
        notified.append(data)

    monkeypatch.setattr("comicfeed.infrastructure.scheduler.check_subscription", _boom)
    monkeypatch.setattr("comicfeed.services.notification.notify_source_error", _notify)

    await run_all_checks(_Mgr(), None)

    # webhook 通知带订阅名与具体错误
    assert len(notified) == 1
    assert notified[0]["reason"] == "search_failed"
    assert notified[0]["subscription"] == "测试订阅"
    assert "Cookie" in notified[0]["error"]

    # failed 事件已落库，摘要邮件会包含它
    from datetime import datetime, timedelta
    async with get_session() as s:
        events = await pending_since(s, datetime.now() - timedelta(hours=1))
    assert len(events) == 1
    assert events[0].status == "failed"
    assert events[0].subscription_id == sub_id
    assert events[0].subscription_name == "测试订阅"
    assert "Cookie" in events[0].error


async def test_dedup_within_batch():
    """同批次内相似标题去重，保留页数多的。"""
    init_db(":memory:")
    await create_tables()

    async with get_session() as session:
        sub = Subscription(name="test", source_key="fake", query="test", mode="SEARCH")
        session.add(sub)
        await session.commit()
        sub_id = sub.id

    source = _FakeSource()
    source.search_results = [
        GallerySummary(native_id="1", title="(C97) My Comic [Digital]", cover_url="", page_count=32),
        GallerySummary(native_id="2", title="My Comic [English]", cover_url="", page_count=30),
        GallerySummary(native_id="3", title="Other Comic", cover_url="", page_count=20),
    ]

    async with get_session() as session:
        new, has_more = await check_subscription(session, sub_id, source)
        # 1 和 2 相似 → 保留页数多的 #1；3 不同 → 保留
        assert len(new) == 2
        ids = {g.native_id for g in new}
        assert ids == {"1", "3"}
