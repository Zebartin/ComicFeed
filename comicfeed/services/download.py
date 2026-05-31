"""下载编排：批量下载 + 通知。"""
from dataclasses import dataclass, field

from comicfeed.log import get
from comicfeed.sources.base import GalleryDetail

_log = get(__name__)


@dataclass
class DownloadTask:
    source_key: str
    gallery_id: str
    output_dir: str
    gallery_url: str = ""
    cbz_max_pages: int = 0
    detail: GalleryDetail | None = None
    append_pages: bool = False
    replaces_native_id: str = ""
    subscription_id: int | None = None
    title: str = ""
    cover_url: str = ""
    page_count: int = 0
    new_page_ids: list[str] = field(default_factory=list)


async def download_batch(
    source, pool, tracker, tasks: list[DownloadTask],
    subscription_name: str = "",
) -> tuple[list[dict], list[dict]]:
    """批量下载，返回 (成功列表, 失败列表)。pool 可为 None（直接调 download_gallery）。"""
    from comicfeed.downloader import download_gallery

    for t in tasks:
        full_gid = f"{t.source_key}:{t.gallery_id}"
        tracker.enqueue(full_gid, title=t.title or t.gallery_id,
                        total_pages=t.page_count,
                        cover_url=t.cover_url, web_url=t.gallery_url,
                        retry_kwargs={
                            "source_key": t.source_key,
                            "gallery_id": t.gallery_id,
                            "output_dir": t.output_dir,
                            "cbz_max_pages": t.cbz_max_pages,
                            "gallery_url": t.gallery_url,
                            "append_pages": t.append_pages,
                            "replaces_native_id": t.replaces_native_id,
                            "subscription_id": t.subscription_id,
                        })

    downloaded = []
    failed = []
    for t in tasks:
        full_gid = f"{t.source_key}:{t.gallery_id}"
        try:
            _log.info("开始下载: %s (%s)", full_gid, t.title)
            if pool:
                result = await pool.download(
                    source, t.gallery_id, t.output_dir,
                    tracker=tracker,
                    gallery_url=t.gallery_url,
                    detail=t.detail,
                    append_pages=t.append_pages,
                    replaces_native_id=t.replaces_native_id,
                    cbz_max_pages=t.cbz_max_pages,
                )
            else:
                result = await download_gallery(
                    source, t.gallery_id, t.output_dir,
                    tracker=tracker,
                    gallery_url=t.gallery_url,
                    detail=t.detail,
                    append_pages=t.append_pages,
                    replaces_native_id=t.replaces_native_id,
                    cbz_max_pages=t.cbz_max_pages,
                )
            downloaded.append({
                "gallery_id": full_gid,
                "title": result.title or t.title,
                "files": result.files,
                "cover_url": result.cover_url or t.cover_url,
                "web_url": result.web_url or t.gallery_url,
                "page_count": result.page_count or t.page_count,
            })
        except Exception as e:
            _log.error("下载失败: %s - %s", full_gid, e)
            tracker.failed(full_gid, str(e),
                           title=t.title, total_pages=t.page_count,
                           cover_url=t.cover_url, web_url=t.gallery_url)
            failed.append({
                "gallery_id": full_gid,
                "title": t.title,
                "error": str(e),
            })

    # 批量通知
    if downloaded or failed:
        from comicfeed.services.notification import notify_batch
        await notify_batch({
            "subscription": subscription_name or "手动下载",
            "galleries": downloaded,
            "count": len(downloaded),
            "failed": failed,
            "failed_count": len(failed),
        })

    return downloaded, failed
