import asyncio
import json
import os

import pytest

from comicfeed.infrastructure.database import create_tables, init_db
from comicfeed.services.download import (
    DownloadPool,
    DownloadResult,
    DownloadTask,
    GallerySkipped,
    download_batch,
    download_gallery,
)
from comicfeed.services.queue import DownloadTracker
from comicfeed.sources.base import (
    AuthSchema,
    BaseSource,
    GalleryDetail,
    SearchResult,
    UpdateResult,
)


@pytest.fixture(autouse=True)
async def _db():
    """test_downloader 需要 DB 读取 download_retry 等设置，自给自足避免依赖其他测试文件先跑 init_db。"""
    init_db(":memory:")
    await create_tables()
    yield


async def test_download_gallery_to_cbz(tmp_path):
    """下载完整画廊并打包为 CBZ 文件。"""
    from comicfeed.sources.nhentai import NhentaiSource

    source = NhentaiSource()
    # 小画廊 103110: 35 pages, split into 2 volumes
    result = await download_gallery(
        source=source,
        gallery_id="103110",
        output_dir=str(tmp_path),
        cbz_max_pages=30,
    )
    assert len(result.files) == 2  # 35 pages / 30 = 2 volumes
    assert result.files[0].endswith("(0001-0030).cbz")
    assert result.files[1].endswith("(0031-0035).cbz")


class _MockSource(BaseSource):
    """测试用：可控制并发数的 mock 源。"""
    key = "mock"
    name = "Mock"
    version = "1.0"
    domains = ["mock.local"]
    auth_schema = AuthSchema.NONE

    def __init__(self, delay=0.1, **kw):
        super().__init__(**kw)
        self.delay = delay
        self.active = 0
        self.max_active = 0

    async def search(self, query, page, sort="date") -> SearchResult:
        return SearchResult()

    async def get_gallery(self, gallery_id, gallery_url="") -> GalleryDetail:
        return GalleryDetail(
            native_id=gallery_id,
            title="Mock Gallery",
            cover_url="",
            web_url="",
            page_urls=["http://mock.local/1.jpg", "http://mock.local/2.jpg"],
            reported_pages=2,
        )

    async def download_pages(self, gallery_id, page_range, gallery_url="", detail=None):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(self.delay)
        result = [b"\xff\xd8\xffMock"] * 2
        self.active -= 1
        return result

    async def check_updates(self, gallery_id, last_known, gallery_url=""):
        return UpdateResult()


async def test_pool_limits_concurrency(tmp_path):
    """max_workers=1 时同时只有一个下载在运行。"""
    s1 = _MockSource(delay=0.1)
    s2 = _MockSource(delay=0.1)
    pool = DownloadPool(max_workers=1)

    async with pool:
        t1 = asyncio.create_task(pool.download(s1, "1", str(tmp_path)))
        t2 = asyncio.create_task(pool.download(s2, "2", str(tmp_path)))
        results = await asyncio.gather(t1, t2)

    assert len(results[0].files) == 1
    assert len(results[1].files) == 1
    # max_workers=1 意味着至少有一个源的 max_active 在任何时刻 ≤ 1
    # 两个源各自独立，但由于全局只有 1 个 worker，并发为 1
    assert s1.max_active <= 1
    assert s2.max_active <= 1


async def test_pool_respects_per_source_limit(tmp_path):
    """每源槽位限制生效。"""
    s1 = _MockSource(delay=0.05)
    pool = DownloadPool(max_workers=5)
    pool.set_source_limit("mock", 2)

    async with pool:
        tasks = [asyncio.create_task(pool.download(s1, str(i), str(tmp_path))) for i in range(4)]
        await asyncio.gather(*tasks)

    # 全局 5 workers，但源限制 2，所以 max_active 不超过 2
    assert s1.max_active <= 2


async def test_download_stage_filter_raises_skipped(tmp_path):
    """下载阶段筛选不合格 → 抛 GallerySkipped（而非 NameError/失败）。"""
    source = _MockSource(delay=0)
    rules = json.dumps([{"field": "num_favorites", "op": "gte", "value": 100}])
    with pytest.raises(GallerySkipped):
        await download_gallery(
            source=source, gallery_id="1", output_dir=str(tmp_path),
            filter_rules=rules,
        )


async def test_download_batch_marks_skipped(tmp_path):
    """download_batch 将筛选跳过的画廊记为 skipped，不记 failed。"""
    source = _MockSource(delay=0)
    tracker = DownloadTracker()
    rules = json.dumps([{"field": "num_favorites", "op": "gte", "value": 100}])
    task = DownloadTask(
        source_key="mock", gallery_id="1", output_dir=str(tmp_path),
        filter_rules=rules, title="Mock Gallery",
    )
    downloaded, failed = await download_batch(source, None, tracker, [task])
    assert downloaded == []
    assert failed == []
    snap = tracker.snapshot()
    assert len(snap["skipped"]) == 1
    assert snap["skipped"][0]["status"] == "skipped"
    assert snap["failed"] == []


async def test_tracker_clear_skipped():
    """clear_skipped 清空已跳过列表。"""
    tracker = DownloadTracker()
    tracker.skipped("mock:1", "不符合订阅筛选条件")
    tracker.skipped("mock:2", "不符合订阅筛选条件")
    assert len(tracker.snapshot()["skipped"]) == 2
    tracker.clear_skipped()
    assert tracker.snapshot()["skipped"] == []


class _ChunkSource(_MockSource):
    """记录 download_pages 收到的分片，用于验证分块下载。"""

    def __init__(self, page_count, **kw):
        super().__init__(**kw)
        self.page_count = page_count
        self.calls = []

    async def get_gallery(self, gallery_id, gallery_url="") -> GalleryDetail:
        return GalleryDetail(
            native_id=gallery_id, title="Mock", cover_url="", web_url="",
            page_urls=[f"http://mock.local/{i}.jpg" for i in range(self.page_count)],
            page_native_ids=[str(i) for i in range(self.page_count)],
            reported_pages=self.page_count,
        )

    async def download_pages(self, gallery_id, page_range, gallery_url="", detail=None):
        self.calls.append((page_range.start, page_range.stop))
        n = page_range.stop - page_range.start
        return [b"\xff\xd8\xffMock"] * n


async def test_fetch_pages_chunks_requests(tmp_path):
    """fetch_pages 分块请求：单次 download_pages 覆盖多页，而非每页一次。"""
    from comicfeed.io.page_fetcher import fetch_pages

    src = _ChunkSource(25)
    detail = await src.get_gallery("g")
    cache_dir = str(tmp_path)
    n = await fetch_pages(src, "g", "", detail, 25, cache_dir)
    assert n == 25
    # 每块 ≤ _CHUNK_SIZE=10，25 页分 3 次请求
    assert src.calls == [(0, 10), (10, 20), (20, 25)]
    # 缓存命中：再次抓取不再触发下载
    src.calls.clear()
    n2 = await fetch_pages(src, "g", "", detail, 25, cache_dir)
    assert n2 == 25
    assert src.calls == []


class _FailingSource(_ChunkSource):
    async def download_pages(self, gallery_id, page_range, gallery_url="", detail=None):
        self.calls.append((page_range.start, page_range.stop))
        raise RuntimeError("boom")


async def test_fetch_pages_does_not_retry(tmp_path):
    """重试折叠：fetch_pages 不重复调用 download_pages，失败直接冒泡（重试由源内部负责）。"""
    from comicfeed.io.page_fetcher import fetch_pages

    src = _FailingSource(25)
    detail = await src.get_gallery("g")
    with pytest.raises(RuntimeError):
        await fetch_pages(src, "g", "", detail, 25, str(tmp_path))
    assert len(src.calls) == 1
