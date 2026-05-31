from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from comicfeed.infrastructure.database import get_session
from comicfeed.infrastructure.log import get
from comicfeed.models import Subscription
from comicfeed.services.subscription import check_subscription
from comicfeed.infrastructure.source_manager import SourceManager

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

            from comicfeed.infrastructure.config import get_setting, get_source_proxy
            from comicfeed.infrastructure.config import get_source_credentials
            creds = await get_source_credentials(sub.source_key)
            proxy = await get_source_proxy(sub.source_key)
            source = source_manager.get_source(sub.source_key, credentials=creds, proxy=proxy)
            if source is None:
                _log.warning("源不可用: %s", sub.source_key)
                from comicfeed.services.notification import notify_source_error
                await notify_source_error({"source_key": sub.source_key, "reason": "not_found"})
                continue

            try:
                new, _ = await check_subscription(session, sub.id, source, max_search_pages=1)
                _log.info("[%s] 检查完成: %d 个新画廊", sub.name, len(new))
            except Exception as e:
                _log.error("[%s] 检查失败: %s", sub.name, e)
                from comicfeed.services.notification import notify_source_error
                await notify_source_error({"source_key": sub.source_key, "reason": "search_failed"})
                continue

            from comicfeed.infrastructure.config import get_setting
            out_dir = sub.download_dir or await get_setting("download_path", ".")
            from comicfeed.web.app import get_download_tracker
            from comicfeed.services.download import DownloadTask, download_batch

            tracker = get_download_tracker()
            tasks = [DownloadTask(
                source_key=source.key, gallery_id=item.native_id,
                output_dir=out_dir, gallery_url=item.web_url,
                cbz_max_pages=sub.cbz_max_pages,
                detail=item.detail, append_pages=bool(item.new_page_ids),
                replaces_native_id=item.replaces_native_id,
                title=item.title, cover_url=item.cover_url or "",
                page_count=item.page_count,
            ) for item in new]

            downloaded, failed = await download_batch(source, download_pool, tracker,
                                                       tasks, subscription_name=sub.name)

            for item in new:
                if item.replaces_native_id:
                    sub.query = item.web_url
                    await session.commit()


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

