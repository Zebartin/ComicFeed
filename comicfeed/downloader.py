import asyncio
import os
from dataclasses import dataclass, field

from comicfeed.cbz import make_cbz_name, normalize_title, pack_cbz
from comicfeed.log import get
from comicfeed.sources.base import BaseSource

_log = get(__name__)


@dataclass
class DownloadResult:
    gallery_id: str
    files: list[str] = field(default_factory=list)


async def download_gallery(
    source: BaseSource,
    gallery_id: str,
    output_dir: str,
    cbz_max_pages: int = 0,
    tracker: "DownloadTracker | None" = None,
    fire_events: bool = True,
    save_to_db: bool = True,
) -> DownloadResult:
    """下载完整画廊并打包为 CBZ。fire_events=False 时不触发事件。"""
    from comicfeed.hooks import Event, bus

    detail = await source.get_gallery(gallery_id)
    title = normalize_title(detail.title)
    total = detail.reported_pages
    if cbz_max_pages <= 0:
        cbz_max_pages = total

    full_gid = f"{source.key}:{gallery_id}"
    if tracker:
        tracker.started(full_gid, title, total, cover_url=detail.cover_url, web_url=detail.web_url)

    result = DownloadResult(gallery_id=full_gid)
    downloaded = 0
    CHUNK = 5  # 每批下载页数，便于更新进度

    for vol_start in range(0, total, cbz_max_pages):
        vol_end = min(vol_start + cbz_max_pages, total)
        vol_pages: list[bytes] = []
        # 分批下载，每批之间更新进度
        for chunk_start in range(vol_start, vol_end, CHUNK):
            chunk_end = min(chunk_start + CHUNK, vol_end)
            try:
                chunk = await source.download_pages(gallery_id, slice(chunk_start, chunk_end))
            except Exception as e:
                _log.error("下载失败: %s 第 %d-%d 页 - %s", gallery_id, chunk_start+1, chunk_end, e)
                raise
            vol_pages.extend(chunk)
            downloaded += len(chunk)
            if tracker:
                tracker.progress(full_gid, downloaded)

        # 广告页检测：从尾部扫描，去掉广告
        from comicfeed.detect_ad import detect_ads_from_tail
        ad_count = detect_ads_from_tail(vol_pages)
        if ad_count > 0:
            _log.info("检测到 %d 页广告 (共 %d 页)", ad_count, len(vol_pages))
            vol_pages = vol_pages[:-ad_count] if ad_count < len(vol_pages) else vol_pages
            downloaded -= ad_count
            if tracker:
                tracker.progress(full_gid, downloaded)

        if vol_pages:
            fname = make_cbz_name(gallery_id, title, vol_start + 1, vol_start + len(vol_pages), total_pages=total)
            fpath = os.path.join(output_dir, fname)
            with open(fpath, "wb") as f:
                pack_cbz(f, fname, detail, vol_pages, start_page=vol_start + 1)
            result.files.append(fpath)

    if tracker:
        tracker.finished(full_gid)

    _log.info("下载完成: %s (%d 页) → %s", full_gid, downloaded, os.path.basename(result.files[0]) if result.files else "")

    if fire_events:
        await bus.fire(Event("gallery.created", {
            "gallery_id": full_gid, "title": title, "files": result.files,
        }))

    # 写入数据库（失败不阻塞）
    if save_to_db:
        try:
            from datetime import datetime
            from comicfeed.database import get_session
            from comicfeed.models import Gallery
            import json
            now = datetime.now()
            async with get_session() as session:
                g = await session.get(Gallery, full_gid)
                if g is None:
                    g = Gallery(id=full_gid, source_key=source.key, native_id=gallery_id,
                                normalized_title=title, display_title=title,
                                cover_url=detail.cover_url,
                                tags=json.dumps(detail.tags, ensure_ascii=False),
                                num_favorites=detail.num_favorites,
                                reported_pages=total, actual_pages=downloaded,
                                downloaded_at=now)
                    session.add(g)
                else:
                    g.actual_pages = downloaded
                    g.reported_pages = total
                    g.cover_url = detail.cover_url
                    g.tags = json.dumps(detail.tags, ensure_ascii=False)
                    g.num_favorites = detail.num_favorites
                    g.downloaded_at = now
                g.file_path = result.files[0] if result.files else None
                await session.commit()
        except Exception:
            pass

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
        tracker: "DownloadTracker | None" = None,
        fire_events: bool = True,
        save_to_db: bool = True,
    ) -> DownloadResult:
        """获取全局和源级信号量后执行下载。"""
        src_sem = self._source_sem(source)
        async with self._global_sem:
            if src_sem:
                async with src_sem:
                    return await download_gallery(source, gallery_id, output_dir, cbz_max_pages, tracker=tracker, fire_events=fire_events, save_to_db=save_to_db)
            else:
                return await download_gallery(source, gallery_id, output_dir, cbz_max_pages, tracker=tracker, fire_events=fire_events, save_to_db=save_to_db)


class DownloadTracker:
    """追踪正在进行的下载任务。"""

    def __init__(self):
        self._tasks: dict[str, dict] = {}

    def started(self, gallery_id: str, title: str, total_pages: int, cover_url: str = "", web_url: str = ""):
        self._tasks[gallery_id] = {
            "gallery_id": gallery_id, "title": title,
            "total_pages": total_pages, "downloaded": 0,
            "cover_url": cover_url, "web_url": web_url,
        }

    def progress(self, gallery_id: str, downloaded: int):
        if gallery_id in self._tasks:
            self._tasks[gallery_id]["downloaded"] = downloaded

    def finished(self, gallery_id: str):
        self._tasks.pop(gallery_id, None)

    def active(self) -> list[dict]:
        return list(self._tasks.values())
