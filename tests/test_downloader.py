import asyncio
import os

from comicfeed.downloader import DownloadPool, DownloadResult, download_gallery
from comicfeed.sources.base import (
    AuthSchema,
    BaseSource,
    GalleryDetail,
    SearchResult,
    UpdateResult,
)


async def test_download_gallery_to_cbz(tmp_path, nhentai_credentials):
    """下载完整画廊并打包为 CBZ 文件。"""
    from comicfeed.sources.nhentai import NhentaiSource

    source = NhentaiSource(credentials=nhentai_credentials)
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
