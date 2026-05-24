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
                "display_title": g.display_title, "normalized_title": g.normalized_title,
                "reported_pages": g.reported_pages, "actual_pages": g.actual_pages,
                "file_path": g.file_path,
            }
            for g in galleries
        ]


@router.post("/download", status_code=202)
async def download_by_id(req: DownloadRequest):
    """按 Gallery ID 或 URL 手动下载（后台任务）。"""
    from comicfeed.web.app import get_source_manager
    mgr = get_source_manager()
    source = mgr.get_source(req.source_key) if mgr else None
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
    out_dir = await get_setting("download_path", ".")
    import asyncio
    from comicfeed.downloader import download_gallery
    asyncio.create_task(download_gallery(source, gid, out_dir))
    return {"status": "accepted", "gallery_id": f"{req.source_key}:{gid}"}
