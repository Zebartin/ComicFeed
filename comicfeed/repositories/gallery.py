"""Gallery 数据访问。"""
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from comicfeed.models import Gallery


async def get_or_create(session: AsyncSession, full_gid: str, source_key: str,
                        native_id: str, title: str, cover_url: str, web_url: str,
                        tags: list[str], num_favorites: int, reported_pages: int,
                        actual_pages: int, file_path: str = "") -> Gallery:
    g = await session.get(Gallery, full_gid)
    now = datetime.now()
    if g is None:
        g = Gallery(
            id=full_gid, source_key=source_key, native_id=native_id,
            normalized_title=title, display_title=title,
            cover_url=cover_url, web_url=web_url,
            tags=json.dumps(tags, ensure_ascii=False),
            num_favorites=num_favorites,
            reported_pages=reported_pages, actual_pages=actual_pages,
            downloaded_at=now,
        )
        session.add(g)
    else:
        g.actual_pages = actual_pages
        g.reported_pages = reported_pages
        g.cover_url = cover_url
        g.web_url = web_url
        g.tags = json.dumps(tags, ensure_ascii=False)
        g.num_favorites = num_favorites
        g.downloaded_at = now
    g.file_path = file_path or None
    return g


async def existing_ids(session: AsyncSession, ids: list[str]) -> set[str]:
    rows = await session.execute(select(Gallery.id).where(Gallery.id.in_(ids)))
    return {row[0] for row in rows.fetchall()}


async def existing_titles(session: AsyncSession, source_key: str) -> list[str]:
    rows = await session.execute(
        select(Gallery.normalized_title).where(Gallery.source_key == source_key)
    )
    return [row[0] for row in rows.fetchall()]
