from comicfeed.database import create_tables, get_session, init_db
from comicfeed.models import Gallery, Subscription
from comicfeed.scheduler import check_subscription
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

    async def download_pages(self, gallery_id, page_range, gallery_url="", detail=None):
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
