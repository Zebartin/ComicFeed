from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from comicfeed.database import get_session
from comicfeed.hooks import Event, bus as event_bus
from comicfeed.log import get
from comicfeed.models import Subscription
from comicfeed.services.subscription import check_subscription
from comicfeed.source_manager import SourceManager

_log = get(__name__)


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

            from comicfeed.config import get_setting, get_source_proxy
            from comicfeed.credentials import get_source_credentials
            creds = await get_source_credentials(sub.source_key)
            proxy = await get_source_proxy(sub.source_key)
            source = source_manager.get_source(sub.source_key, credentials=creds, proxy=proxy)
            if source is None:
                _log.warning("源不可用: %s", sub.source_key)
                await event_bus.fire(Event("source.error", {"source_key": sub.source_key, "reason": "not_found"}))
                continue

            try:
                new, _ = await check_subscription(session, sub.id, source, max_search_pages=1)
                _log.info("[%s] 检查完成: %d 个新画廊", sub.name, len(new))
            except Exception as e:
                _log.error("[%s] 检查失败: %s", sub.name, e)
                await event_bus.fire(Event("source.error", {"source_key": sub.source_key, "reason": "search_failed"}))
                continue

            downloaded = []
            failed = []
            from comicfeed.config import get_setting
            out_dir = sub.download_dir or await get_setting("download_path", ".")
            from comicfeed.web.app import get_download_tracker
            from comicfeed.models import Page, SubscriptionGallery
            tracker = get_download_tracker()

            # 一次性全部入列
            for item in new:
                gid = f"{source.key}:{item.native_id}"
                tracker.enqueue(gid, title=item.title, total_pages=item.page_count,
                                cover_url=item.cover_url or "", web_url=item.web_url or "",
                                retry_kwargs={"source_key": source.key, "gallery_id": item.native_id,
                                              "output_dir": out_dir, "cbz_max_pages": sub.cbz_max_pages,
                                              "gallery_url": item.web_url,
                                              "append_pages": bool(item.new_page_ids),
                                              "replaces_native_id": item.replaces_native_id})

            for item in new:
                gid = f"{source.key}:{item.native_id}"
                try:
                    _log.info("开始下载: %s (%s)", gid, item.title)
                    result = await download_pool.download(source, item.native_id, out_dir, tracker=tracker, fire_events=False, gallery_url=item.web_url, detail=item.detail, append_pages=bool(item.new_page_ids), replaces_native_id=item.replaces_native_id, cbz_max_pages=sub.cbz_max_pages)
                    sg = await session.get(SubscriptionGallery, (sub.id, gid))
                    if sg is None:
                        session.add(SubscriptionGallery(subscription_id=sub.id, gallery_id=gid))
                        await session.commit()
                    # newer version：更新订阅 URL
                    if item.replaces_native_id:
                        sub.query = item.web_url
                        await session.commit()
                    downloaded.append({"id": gid, "title": result.title or item.title, "files": result.files, "cover_url": result.cover_url or item.cover_url, "web_url": result.web_url or item.web_url, "page_count": result.page_count or item.page_count})
                except Exception as e:
                    _log.error("下载失败: %s - %s", gid, e)
                    tracker.failed(gid, str(e), title=item.title, total_pages=item.page_count,
                                   cover_url=item.cover_url or "", web_url=item.web_url or "")
                    failed.append({"id": gid, "title": item.title, "error": str(e)})

            # 批量通知
            if downloaded or failed:
                await event_bus.fire(Event("gallery.created", {
                    "subscription": sub.name,
                    "source_key": sub.source_key,
                    "galleries": [{
                        "gallery_id": d["id"], "title": d["title"],
                        "files": d["files"], "cover_url": d.get("cover_url", ""),
                        "web_url": d.get("web_url", ""), "page_count": d.get("page_count", 0),
                    } for d in downloaded],
                    "count": len(downloaded),
                    "failed": [{"gallery_id": f["id"], "title": f["title"], "error": f.get("error", "")} for f in failed],
                    "failed_count": len(failed),
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

