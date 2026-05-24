from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from comicfeed.database import get_session
from comicfeed.models import Gallery

router = APIRouter(prefix="/api/galleries", tags=["galleries"])


class DownloadRequest(BaseModel):
    source_key: str
    gallery_id: str
    url: str | None = None


@router.get("")
async def list_galleries(source_key: str | None = None, limit: int = 50, offset: int = 0):
    async with get_session() as session:
        stmt = select(Gallery).order_by(Gallery.downloaded_at.desc()).offset(offset).limit(limit)
        if source_key:
            stmt = stmt.where(Gallery.source_key == source_key)
        result = await session.execute(stmt)
        galleries = result.scalars().all()
        return [
            {
                "id": g.id, "source_key": g.source_key, "native_id": g.native_id,
                "display_title": g.display_title, "cover_url": g.cover_url,
                "tags": _parse_tags(g.tags), "num_favorites": g.num_favorites,
                "reported_pages": g.reported_pages, "actual_pages": g.actual_pages,
                "file_path": g.file_path,
                "web_url": f"https://nhentai.net/g/{g.native_id}/",
            }
            for g in galleries
        ]


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
    from comicfeed.credentials import get_source_credentials
    mgr = get_source_manager()
    creds = await get_source_credentials(req.source_key)
    source = mgr.get_source(req.source_key, credentials=creds) if mgr else None
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
    import asyncio
    from comicfeed.downloader import download_gallery
    asyncio.create_task(download_gallery(source, gid, out_dir, tracker=tracker))
    return {"status": "accepted", "gallery_id": f"{req.source_key}:{gid}"}
