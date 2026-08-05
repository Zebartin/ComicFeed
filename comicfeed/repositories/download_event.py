"""DownloadEvent 数据访问。"""
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from comicfeed.models import DownloadEvent


async def record_event(session: AsyncSession, *, subscription_id: int | None = None,
                       subscription_name: str = "", source_key: str = "",
                       gallery_id: str = "", title: str = "", cover_url: str = "",
                       web_url: str = "", page_count: int = 0,
                       status: str = "success", error: str = ""):
    """记录一次下载事件（成功或失败）。调用方负责 commit。"""
    session.add(DownloadEvent(
        subscription_id=subscription_id,
        subscription_name=subscription_name,
        source_key=source_key,
        gallery_id=gallery_id,
        title=title,
        cover_url=cover_url,
        web_url=web_url,
        page_count=page_count,
        status=status,
        error=error,
    ))


async def pending_since(session: AsyncSession, since) -> list[DownloadEvent]:
    """返回 created_at > since 的事件，按时间升序。"""
    rows = await session.execute(
        select(DownloadEvent)
        .where(DownloadEvent.created_at > since)
        .order_by(DownloadEvent.created_at)
    )
    return rows.scalars().all()


async def delete_before(session: AsyncSession, cutoff) -> int:
    """删除 created_at <= cutoff 的事件，返回删除条数。"""
    result = await session.execute(
        delete(DownloadEvent).where(DownloadEvent.created_at <= cutoff)
    )
    return result.rowcount or 0
