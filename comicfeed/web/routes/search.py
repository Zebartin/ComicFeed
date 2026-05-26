"""快速搜索 API：不依赖订阅，直接搜索源。"""
from fastapi import APIRouter
from pydantic import BaseModel

from comicfeed.config import get_source_proxy
from comicfeed.credentials import get_source_credentials

router = APIRouter(prefix="/api/search", tags=["search"])


class SearchRequest(BaseModel):
    source_key: str
    query: str
    sort: str = "date"
    page: int = 1
    next_url: str = ""
    exclude_ids: list[str] = []
    existing_titles: list[str] = []


@router.post("")
async def search_source(req: SearchRequest):
    from comicfeed.web.app import get_source_manager
    mgr = get_source_manager()
    creds = await get_source_credentials(req.source_key)
    proxy = await get_source_proxy(req.source_key)
    source = mgr.get_source(req.source_key, credentials=creds, proxy=proxy)
    if source is None:
        return {"error": f"源 {req.source_key} 不可用", "items": []}

    if req.next_url and hasattr(source, '_next_url'):
        source._next_url = req.next_url

    result = await source.search(req.query, page=req.page, sort=req.sort)
    next_url = getattr(source, '_next_url', '')

    # 去重
    exclude_ids = set(req.exclude_ids)
    from comicfeed.cbz import normalize_title
    from comicfeed.dedup import _similarity, find_similar_groups, resolve_duplicates

    # 1. 排掉 exclude_ids
    raw = [g for g in result.items if g.native_id not in exclude_ids]
    # 2. 标题去重
    filtered = []
    for g in raw:
        nt = normalize_title(g.title)
        if any(_similarity(nt, et) > 0.999 for et in req.existing_titles):
            continue
        filtered.append(g)
        req.existing_titles.append(nt)
    # 3. 批次内去重
    groups = find_similar_groups(filtered)
    if groups:
        keep: set[str] = {g.native_id for g in filtered}
        for group in groups:
            candidates = [(g.native_id, g.page_count) for g in group]
            res = resolve_duplicates(candidates)
            keep -= {g.native_id for g in group}
            keep |= res
        filtered = [g for g in filtered if g.native_id in keep]

    return {
        "items": [{
            "native_id": g.native_id, "title": g.title,
            "page_count": g.page_count, "cover_url": g.cover_url,
            "web_url": g.web_url, "num_favorites": g.num_favorites,
            "tags": g.tags[:6],
        } for g in filtered],
        "has_more": bool(next_url or result.total_pages > req.page),
        "next_url": next_url,
        "current_page": req.page,
    }
