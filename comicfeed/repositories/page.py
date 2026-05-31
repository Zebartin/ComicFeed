"""Page 数据访问。"""
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from comicfeed.models import Page


async def count_for_gallery(session: AsyncSession, gallery_id: str) -> int:
    result = await session.execute(
        select(func.count()).where(Page.gallery_id == gallery_id)
    )
    return result.scalar() or 0


async def ids_for_gallery(session: AsyncSession, gallery_id: str) -> list[str]:
    rows = await session.execute(
        select(Page.page_native_id).where(Page.gallery_id == gallery_id)
    )
    return [row[0] for row in rows.fetchall()]


async def replace_all(session: AsyncSession, gallery_id: str,
                      page_native_ids: list[str]):
    await session.execute(delete(Page).where(Page.gallery_id == gallery_id))
    for pid in page_native_ids:
        session.add(Page(gallery_id=gallery_id, page_native_id=pid))


async def append_new(session: AsyncSession, gallery_id: str,
                     page_native_ids: list[str]):
    for pid in page_native_ids:
        session.add(Page(gallery_id=gallery_id, page_native_id=pid))


async def migrate_gallery(session: AsyncSession, old_gid: str, new_gid: str):
    await session.execute(
        update(Page).where(Page.gallery_id == old_gid).values(gallery_id=new_gid)
    )


async def delete_for_gallery(session: AsyncSession, gallery_id: str):
    await session.execute(delete(Page).where(Page.gallery_id == gallery_id))
