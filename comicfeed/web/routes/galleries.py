from fastapi import APIRouter
from sqlalchemy import select

from comicfeed.database import get_session
from comicfeed.models import Gallery

router = APIRouter(prefix="/api/galleries", tags=["galleries"])


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
