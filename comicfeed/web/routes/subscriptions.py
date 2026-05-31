from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from comicfeed.infrastructure.database import get_session
from comicfeed.infrastructure.log import get
from comicfeed.models import Subscription

_log = get(__name__)

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


class SubCreate(BaseModel):
    name: str
    source_key: str
    query: str
    mode: str = "SEARCH"
    interval_minutes: int = 360
    cbz_max_pages: int = 30
    sort: str = "date"
    download_dir: str = ""
    filter_rules: str = ""
    enabled: bool = True


class SubUpdate(BaseModel):
    name: str | None = None
    source_key: str | None = None
    query: str | None = None
    mode: str | None = None
    interval_minutes: int | None = None
    cbz_max_pages: int | None = None
    sort: str | None = None
    download_dir: str | None = None
    filter_rules: str | None = None
    enabled: bool | None = None


@router.get("")
async def list_subscriptions():
    async with get_session() as session:
        from sqlalchemy import select
        result = await session.execute(select(Subscription))
        subs = result.scalars().all()
        return [
            {
                "id": s.id, "name": s.name, "source_key": s.source_key,
                "query": s.query, "mode": s.mode, "interval_minutes": s.interval_minutes,
                "cbz_max_pages": s.cbz_max_pages, "sort": s.sort,
                "download_dir": s.download_dir, "filter_rules": s.filter_rules, "enabled": s.enabled,
            }
            for s in subs
        ]


@router.post("", status_code=201)
async def create_subscription(data: SubCreate):
    async with get_session() as session:
        sub = Subscription(**data.model_dump())
        session.add(sub)
        await session.commit()
        await session.refresh(sub)
        _log.info("创建订阅: %s [%s] query=%s", sub.name, sub.source_key, sub.query)
        return _sub_to_dict(sub)


@router.get("/{sub_id}")
async def get_subscription(sub_id: int):
    async with get_session() as session:
        sub = await session.get(Subscription, sub_id)
        if sub is None:
            raise HTTPException(404, "未找到")
        return _sub_to_dict(sub)


@router.put("/{sub_id}")
async def update_subscription(sub_id: int, data: SubUpdate):
    async with get_session() as session:
        sub = await session.get(Subscription, sub_id)
        if sub is None:
            raise HTTPException(404, "未找到")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(sub, field, value)
        await session.commit()
        await session.refresh(sub)
        _log.info("更新订阅: #%d %s", sub_id, sub.name)
        return _sub_to_dict(sub)


@router.delete("/{sub_id}", status_code=204)
async def delete_subscription(sub_id: int):
    async with get_session() as session:
        sub = await session.get(Subscription, sub_id)
        if sub is None:
            raise HTTPException(404, "未找到")
        await session.delete(sub)
        _log.info("删除订阅: #%d %s", sub_id, sub.name)
        await session.commit()


class CheckRequest(BaseModel):
    max_search_pages: int = 5
    page: int = 1
    exclude_ids: list[str] = []
    existing_titles: list[str] = []
    next_url: str = ""


@router.post("/{sub_id}/check")
async def check_subscription_now(sub_id: int, req: CheckRequest | None = None):
    if req is None:
        req = CheckRequest()
    from comicfeed.web.app import get_source_manager
    async with get_session() as session:
        sub = await session.get(Subscription, sub_id)
        if sub is None:
            raise HTTPException(404, "未找到")
        mgr = get_source_manager()
        from comicfeed.infrastructure.config import get_source_proxy
        from comicfeed.infrastructure.config import get_source_credentials
        creds = await get_source_credentials(sub.source_key)
        proxy = await get_source_proxy(sub.source_key)
        source = mgr.get_source(sub.source_key, credentials=creds, proxy=proxy) if mgr else None
        if source is None:
            return {"error": f"源 {sub.source_key} 不可用", "new_galleries": []}
        if req.next_url and hasattr(source, '_next_url'):
            source._next_url = req.next_url
        from comicfeed.infrastructure.scheduler import check_subscription
        _log.info("手动检查订阅: %s [%s]", sub.name, sub.source_key)
        new, has_more = await check_subscription(
            session, sub_id, source,
            max_search_pages=req.max_search_pages,
            exclude_ids=set(req.exclude_ids),
            existing_titles=req.existing_titles,
            start_page=req.page,
        )
        _log.info("检查完成: 发现 %d 个新画廊, has_more=%s", len(new), has_more)
        return {
            "subscription": {"id": sub.id, "name": sub.name, "source_key": sub.source_key, "query": sub.query},
            "new_galleries": [{
                "native_id": g.native_id, "title": g.title,
                "page_count": g.page_count, "cover_url": g.cover_url,
                "web_url": g.web_url, "num_favorites": g.num_favorites,
                "tags": g.tags[:6],
                "new_page_ids": g.new_page_ids,
                "replaces_native_id": g.replaces_native_id,
            } for g in new],
            "has_more": has_more,
            "current_page": req.page + req.max_search_pages,
            "next_url": getattr(source, '_next_url', ''),
        }


def _sub_to_dict(s: Subscription) -> dict:
    return {
        "id": s.id, "name": s.name, "source_key": s.source_key,
        "query": s.query, "mode": s.mode, "interval_minutes": s.interval_minutes,
        "sort": s.sort, "download_dir": s.download_dir, "filter_rules": s.filter_rules, "enabled": s.enabled,
    }
