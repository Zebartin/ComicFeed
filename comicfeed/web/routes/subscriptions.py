from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from comicfeed.database import get_session
from comicfeed.models import Subscription

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


class SubCreate(BaseModel):
    name: str
    source_key: str
    query: str
    mode: str = "SEARCH"
    interval_minutes: int = 360
    cbz_max_pages: int = 30
    cross_source_dedup: bool = True
    sort: str = "date"
    enabled: bool = True


class SubUpdate(BaseModel):
    name: str | None = None
    source_key: str | None = None
    query: str | None = None
    mode: str | None = None
    interval_minutes: int | None = None
    cbz_max_pages: int | None = None
    cross_source_dedup: bool | None = None
    sort: str | None = None
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
                "cbz_max_pages": s.cbz_max_pages, "cross_source_dedup": s.cross_source_dedup,
                "enabled": s.enabled,
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
        return _sub_to_dict(sub)


@router.delete("/{sub_id}", status_code=204)
async def delete_subscription(sub_id: int):
    async with get_session() as session:
        sub = await session.get(Subscription, sub_id)
        if sub is None:
            raise HTTPException(404, "未找到")
        await session.delete(sub)
        await session.commit()


@router.post("/{sub_id}/check")
async def check_subscription_now(sub_id: int):
    from comicfeed.web.app import get_source_manager
    async with get_session() as session:
        sub = await session.get(Subscription, sub_id)
        if sub is None:
            raise HTTPException(404, "未找到")
        mgr = get_source_manager()
        from comicfeed.credentials import get_source_credentials
        creds = await get_source_credentials(sub.source_key)
        source = mgr.get_source(sub.source_key, credentials=creds) if mgr else None
        if source is None:
            return {"error": f"源 {sub.source_key} 不可用", "new_galleries": []}
        from comicfeed.scheduler import check_subscription
        new = await check_subscription(session, sub_id, source)
        return {"new_galleries": [{"native_id": g.native_id, "title": g.title} for g in new]}


def _sub_to_dict(s: Subscription) -> dict:
    return {
        "id": s.id, "name": s.name, "source_key": s.source_key,
        "query": s.query, "mode": s.mode, "interval_minutes": s.interval_minutes,
        "cbz_max_pages": s.cbz_max_pages, "cross_source_dedup": s.cross_source_dedup,
        "sort": s.sort, "enabled": s.enabled,
    }
