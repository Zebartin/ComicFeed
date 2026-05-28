from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from comicfeed.database import get_session
from comicfeed.log import get
from comicfeed.models import Gallery, SubscriptionGallery

import asyncio

_log = get(__name__)

router = APIRouter(prefix="/api/galleries", tags=["galleries"])


class DownloadRequest(BaseModel):
    source_key: str
    gallery_id: str
    url: str | None = None


class BatchDownloadRequest(BaseModel):
    source_key: str
    gallery_ids: list[str]
    gallery_metas: dict[str, dict] = {}
    subscription_id: int | None = None


_SORT_FIELDS = {
    "date": Gallery.downloaded_at,
    "id": Gallery.id,
    "pages": Gallery.reported_pages,
    "favorites": Gallery.num_favorites,
    "title": Gallery.display_title,
}


@router.get("")
async def list_galleries(source_key: str | None = None, sort: str = "date",
                         sort_dir: str = "desc", limit: int = 50, offset: int = 0):
    async with get_session() as session:
        # 总数
        count_stmt = select(Gallery.id)
        if source_key:
            count_stmt = count_stmt.where(Gallery.source_key == source_key)
        total = (await session.execute(count_stmt)).fetchall()

        # 排序
        order_col = _SORT_FIELDS.get(sort, Gallery.downloaded_at)
        order = order_col.desc() if sort_dir == "desc" else order_col.asc()

        stmt = select(Gallery).order_by(order).offset(offset).limit(limit)
        if source_key:
            stmt = stmt.where(Gallery.source_key == source_key)
        result = await session.execute(stmt)
        galleries = result.scalars().all()
        return {
            "total": len(total),
            "items": [
                {
                    "id": g.id, "source_key": g.source_key, "native_id": g.native_id,
                    "display_title": g.display_title, "cover_url": g.cover_url,
                    "tags": _parse_tags(g.tags), "num_favorites": g.num_favorites,
                    "reported_pages": g.reported_pages, "actual_pages": g.actual_pages,
                    "file_path": g.file_path, "downloaded_at": _fmt_time(g.downloaded_at),
                    "web_url": _web_url(g.source_key, g.native_id, g.web_url),
                }
                for g in galleries
            ],
        }


def _fmt_time(dt) -> str:
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d")


def _web_url(source_key: str, native_id: str, stored_url: str = "") -> str:
    if stored_url:
        return stored_url
    if source_key == "nhentai":
        return f"https://nhentai.net/g/{native_id}/"
    if source_key == "exhentai":
        return f"https://exhentai.org/?f_search=gid:{native_id}"
    return ""


@router.delete("/{gallery_id}", status_code=204)
async def delete_gallery(gallery_id: str):
    async with get_session() as session:
        g = await session.get(Gallery, gallery_id)
        if g is None:
            raise HTTPException(404, "未找到")
        session.expunge(g)  # 从 session 分离，避免 cascade
        from sqlalchemy import text
        await session.execute(text("DELETE FROM subscription_gallery WHERE gallery_id = :gid"), {"gid": gallery_id})
        await session.execute(text("DELETE FROM page WHERE gallery_id = :gid"), {"gid": gallery_id})
        await session.execute(text("DELETE FROM gallery WHERE id = :gid"), {"gid": gallery_id})
        await session.commit()


def _parse_tags(raw: str) -> list[str]:
    import json
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


@router.post("/download", status_code=202)
async def download_by_id(req: DownloadRequest):
    """按 Gallery ID 或 URL 手动下载（后台任务）。"""
    from comicfeed.web.app import get_source_manager
    from comicfeed.config import get_source_proxy
    from comicfeed.credentials import get_source_credentials
    mgr = get_source_manager()
    creds = await get_source_credentials(req.source_key)
    proxy = await get_source_proxy(req.source_key)
    source = mgr.get_source(req.source_key, credentials=creds, proxy=proxy) if mgr else None
    if source is None:
        return {"status": "error", "error": f"源 {req.source_key} 不可用"}
    # 解析 URL → gallery_id
    gid = req.gallery_id
    if req.url:
        parsed = source.parse_url(req.url)
        if parsed:
            gid = parsed.split(":", 1)[1]
        else:
            return {"error": "无法解析 URL"}
    # 返回已接受，后台执行下载
    from comicfeed.config import get_setting
    from comicfeed.web.app import get_download_tracker
    out_dir = await get_setting("download_path", ".")
    tracker = get_download_tracker()
    full_gid = f"{req.source_key}:{gid}"
    tracker.enqueue(full_gid)
    import asyncio
    from comicfeed.downloader import download_gallery
    async def _dl():
        try:
            await download_gallery(source, gid, out_dir, tracker=tracker, gallery_url=req.url or "")
        except Exception as e:
            tracker.failed(full_gid, str(e))
    asyncio.create_task(_dl())
    _log.info("提交下载: %s:%s", req.source_key, gid)
    return {"status": "accepted", "gallery_id": f"{req.source_key}:{gid}"}


@router.post("/batch-download", status_code=202)
async def batch_download(req: BatchDownloadRequest):
    """批量下载，全部完成后统一通知。"""
    from comicfeed.web.app import get_source_manager, get_download_tracker
    from comicfeed.config import get_source_proxy, get_setting
    from comicfeed.credentials import get_source_credentials
    mgr = get_source_manager()
    creds = await get_source_credentials(req.source_key)
    proxy = await get_source_proxy(req.source_key)
    source = mgr.get_source(req.source_key, credentials=creds, proxy=proxy)
    if source is None:
        return {"status": "error", "error": f"源 {req.source_key} 不可用"}
    # 优先使用订阅级下载目录
    sub_down_dir = ""
    if req.subscription_id:
        from comicfeed.models import Subscription
        from comicfeed.database import get_session
        async with get_session() as s:
            sub = await s.get(Subscription, req.subscription_id)
            if sub and sub.download_dir:
                sub_down_dir = sub.download_dir
    out_dir = sub_down_dir or await get_setting("download_path", ".")
    tracker = get_download_tracker()

    async def _batch():
        from comicfeed.downloader import download_gallery
        from comicfeed.hooks import Event, bus
        # 一次性全部入列
        for gid in req.gallery_ids:
            meta = req.gallery_metas.get(gid, {})
            tracker.enqueue(f"{req.source_key}:{gid}",
                            title=meta.get("title", gid),
                            total_pages=meta.get("page_count", 0),
                            cover_url=meta.get("cover_url", ""),
                            web_url=meta.get("web_url", ""))
        downloaded = []
        for gid in req.gallery_ids:
            full_gid = f"{req.source_key}:{gid}"
            try:
                meta = req.gallery_metas.get(gid, {})
                result = await download_gallery(source, gid, out_dir, tracker=tracker, fire_events=False, gallery_url=meta.get("web_url", ""))
                downloaded.append({
                    "gallery_id": full_gid,
                    "title": result.title, "files": result.files,
                    "cover_url": result.cover_url, "web_url": result.web_url,
                    "page_count": result.page_count,
                })
            except Exception as e:
                _log.error("下载失败: %s:%s - %s", req.source_key, gid, e)
                tracker.failed(full_gid, str(e))
        if downloaded:
            await bus.fire(Event("gallery.created", {
                "subscription": f"手动下载 ({req.source_key})",
                "galleries": downloaded,
                "count": len(downloaded),
            }))
    asyncio.create_task(_batch())
    _log.info("提交批量下载: %s, %d 个画廊", req.source_key, len(req.gallery_ids))
    return {"status": "accepted", "count": len(req.gallery_ids)}
