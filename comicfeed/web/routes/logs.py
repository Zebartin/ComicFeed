from fastapi import APIRouter
from sqlalchemy import select

from comicfeed.database import get_session
from comicfeed.models import SystemLog

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
async def list_logs(level: str | None = None, limit: int = 100, offset: int = 0):
    async with get_session() as session:
        stmt = select(SystemLog).order_by(SystemLog.id.desc()).offset(offset).limit(limit)
        if level:
            stmt = stmt.where(SystemLog.level == level.upper())
        result = await session.execute(stmt)
        logs = result.scalars().all()
        return [
            {
                "id": l.id, "timestamp": l.timestamp.isoformat() if l.timestamp else "",
                "level": l.level, "source": l.source, "message": l.message,
            }
            for l in logs
        ]
