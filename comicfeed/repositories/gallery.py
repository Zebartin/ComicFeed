"""Gallery 数据访问。"""
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from comicfeed.models import Gallery


async def get_or_create(session: AsyncSession, full_gid: str, source_key: str,
                        native_id: str, title: str, cover_url: str, web_url: str,
                        tags: list[str], num_favorites: int, reported_pages: int,
                        actual_pages: int, append_pages: bool = False,
                        page_native_ids: list[str] | None = None) -> Gallery:
    g = await session.get(Gallery, full_gid)
    now = datetime.now()
    if g is None:
        g = Gallery(
            id=full_gid, source_key=source_key, native_id=native_id,
            normalized_title=title,
            cover_url=cover_url, web_url=web_url,
            tags=json.dumps(tags, ensure_ascii=False),
            num_favorites=num_favorites,
            reported_pages=reported_pages, actual_pages=actual_pages,
            downloaded_at=now,
        )
        session.add(g)
    elif append_pages:
        # 增量追加：按「真正新增的页」累加计数与标签并集，标题/封面/来源保留旧值
        from comicfeed.repositories.page import ids_for_gallery
        existing = set(await ids_for_gallery(session, full_gid))
        new_pids = [p for p in (page_native_ids or []) if p not in existing]
        if new_pids:
            g.reported_pages += reported_pages
            g.actual_pages += actual_pages
            old_tags = set(json.loads(g.tags or "[]"))
            g.tags = json.dumps(sorted(old_tags | set(tags)), ensure_ascii=False)
        g.downloaded_at = now
    else:
        g.actual_pages = actual_pages
        g.reported_pages = reported_pages
        g.cover_url = cover_url
        g.web_url = web_url
        g.tags = json.dumps(tags, ensure_ascii=False)
        g.num_favorites = num_favorites
        g.downloaded_at = now
    return g


async def existing_ids(session: AsyncSession, ids: list[str]) -> set[str]:
    rows = await session.execute(select(Gallery.id).where(Gallery.id.in_(ids)))
    return {row[0] for row in rows.fetchall()}


async def existing_titles(session: AsyncSession, source_key: str) -> list[str]:
    rows = await session.execute(
        select(Gallery.normalized_title).where(Gallery.source_key == source_key)
    )
    return [row[0] for row in rows.fetchall()]
