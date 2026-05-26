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

    return {
        "items": [{
            "native_id": g.native_id, "title": g.title,
            "page_count": g.page_count, "cover_url": g.cover_url,
            "web_url": g.web_url, "num_favorites": g.num_favorites,
            "tags": g.tags[:6],
        } for g in result.items],
        "has_more": bool(next_url or result.total_pages > req.page),
        "next_url": next_url,
        "current_page": req.page,
    }
