from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from comicfeed.database import get_session
from comicfeed.hooks import Event, bus as event_bus
from comicfeed.log import get
from comicfeed.models import Gallery, Subscription
from comicfeed.source_manager import SourceManager
from comicfeed.sources.base import BaseSource, GallerySummary

_log = get(__name__)


async def check_subscription(
    session: AsyncSession,
    subscription_id: int,
    source: BaseSource,
) -> list[GallerySummary]:
    """检查一个订阅，返回新发现的画廊摘要列表。"""
    sub = await session.get(Subscription, subscription_id)
    if sub is None:
        return []

    result = await source.search(sub.query, page=1, sort=sub.sort)
    if not result.items:
        return []

    # 查询 DB 中已存在于该源的画廊 ID
    ids = [f"{source.key}:{item.native_id}" for item in result.items]
    stmt = select(Gallery.id).where(Gallery.id.in_(ids))
    existing = {row[0] for row in (await session.execute(stmt)).fetchall()}

    new = []
    for item in result.items:
        if f"{source.key}:{item.native_id}" not in existing:
            new.append(item)

    sub.last_checked_at = datetime.now()
    await session.commit()

    _log.info("订阅 [%s] 检查完成: %d 个新画廊", sub.name, len(new))
    return new


async def run_all_checks(source_manager: SourceManager, download_pool):
    """遍历所有启用的订阅，仅检查间隔已到的。"""
    now = datetime.now()
    async with get_session() as session:
        subs = (await session.scalars(select(Subscription).where(Subscription.enabled == True))).all()
        _log.info("开始巡检: %d 个启用订阅", len(subs))

        for sub in subs:
            # 未到检查间隔，跳过
            if sub.last_checked_at and sub.interval_minutes > 0:
                elapsed = (now - sub.last_checked_at).total_seconds() / 60
                if elapsed < sub.interval_minutes:
                    _log.debug("跳过 [%s]: 距上次检查 %.0f 分钟 (间隔 %d)", sub.name, elapsed, sub.interval_minutes)
                    continue

            _log.info("检查订阅: %s [%s] query=%s", sub.name, sub.source_key, sub.query)

            from comicfeed.config import get_setting
            from comicfeed.credentials import get_source_credentials
            creds = await get_source_credentials(sub.source_key)
            proxy = await get_setting("proxy", "") or None
            source = source_manager.get_source(sub.source_key, credentials=creds, proxy=proxy)
            if source is None:
                _log.warning("源不可用: %s", sub.source_key)
                await event_bus.fire(Event("source.error", {"source_key": sub.source_key, "reason": "not_found"}))
                continue

            try:
                new = await check_subscription(session, sub.id, source)
                _log.info("[%s] 检查完成: %d 个新画廊", sub.name, len(new))
            except Exception as e:
                _log.error("[%s] 检查失败: %s", sub.name, e)
                await event_bus.fire(Event("source.error", {"source_key": sub.source_key, "reason": "search_failed"}))
                continue

            for item in new:
                try:
                    from comicfeed.config import get_setting
                    out_dir = await get_setting("download_path", ".")
                    _log.info("开始下载: %s:%s (%s)", source.key, item.native_id, item.title)
                    from comicfeed.web.app import get_download_tracker
                    result = await download_pool.download(source, item.native_id, out_dir, tracker=get_download_tracker())
                    # 写入订阅-画廊关联
                    from comicfeed.models import SubscriptionGallery
                    gid = f"{source.key}:{item.native_id}"
                    sg = await session.get(SubscriptionGallery, (sub.id, gid))
                    if sg is None:
                        session.add(SubscriptionGallery(subscription_id=sub.id, gallery_id=gid))
                        await session.commit()
                    await event_bus.fire(Event("gallery.created", {
                        "gallery_id": f"{source.key}:{item.native_id}",
                        "title": item.title,
                        "files": result.files,
                    }))
                except Exception as e:
                    _log.error("下载失败: %s:%s - %s", source.key, item.native_id, e)
                    await event_bus.fire(Event("gallery.failed", {
                        "gallery_id": f"{source.key}:{item.native_id}",
                        "title": item.title,
                    }))


def create_scheduler(source_manager: SourceManager, download_pool, interval_minutes: int = 10) -> AsyncIOScheduler:
    """创建 APScheduler 实例，注册定时检查任务。"""
    scheduler = AsyncIOScheduler()

    async def _job():
        await run_all_checks(source_manager, download_pool)

    scheduler.add_job(
        _job,
        "interval",
        minutes=interval_minutes,
        id="check_all_subscriptions",
    )
    return scheduler

