import asyncio
import os
from dataclasses import dataclass, field

from comicfeed.cbz import make_cbz_name, normalize_title, pack_cbz
from comicfeed.sources.base import BaseSource


@dataclass
class DownloadResult:
    gallery_id: str
    files: list[str] = field(default_factory=list)


async def download_gallery(
    source: BaseSource,
    gallery_id: str,
    output_dir: str,
    cbz_max_pages: int = 0,
) -> DownloadResult:
    """下载完整画廊并打包为 CBZ。"""
    detail = await source.get_gallery(gallery_id)
    title = normalize_title(detail.title)
    total = detail.reported_pages
    if cbz_max_pages <= 0:
        cbz_max_pages = total

    result = DownloadResult(gallery_id=gallery_id)

    for vol_start in range(0, total, cbz_max_pages):
        vol_end = min(vol_start + cbz_max_pages, total)
        pages = await source.download_pages(gallery_id, slice(vol_start, vol_end))
        fname = make_cbz_name(gallery_id, title, vol_start + 1, vol_end)
        fpath = os.path.join(output_dir, fname)
        with open(fpath, "wb") as f:
            pack_cbz(f, fname, detail, pages, start_page=vol_start + 1)
        result.files.append(fpath)

    return result


class DownloadPool:
    """全局 worker 池 + 每源队列控制并发下载。"""

    def __init__(self, max_workers: int = 5):
        self._global_sem = asyncio.Semaphore(max_workers)
        self._source_limits: dict[str, asyncio.Semaphore] = {}

    def set_source_limit(self, source_key: str, max_slots: int):
        self._source_limits[source_key] = asyncio.Semaphore(max_slots)

    def _source_sem(self, source: BaseSource) -> asyncio.Semaphore | None:
        return self._source_limits.get(source.key)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def download(
        self,
        source: BaseSource,
        gallery_id: str,
        output_dir: str,
        cbz_max_pages: int = 0,
    ) -> DownloadResult:
        """获取全局和源级信号量后执行下载。"""
        src_sem = self._source_sem(source)
        async with self._global_sem:
            if src_sem:
                async with src_sem:
                    return await download_gallery(source, gallery_id, output_dir, cbz_max_pages)
            else:
                return await download_gallery(source, gallery_id, output_dir, cbz_max_pages)
