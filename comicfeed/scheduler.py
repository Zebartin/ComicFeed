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
    max_search_pages: int = 1,
    exclude_ids: set[str] | None = None,
    existing_titles: list[str] | None = None,
    start_page: int = 1,
) -> tuple[list[GallerySummary], bool]:
    """检查一个订阅，返回 (新画廊列表, 是否还有更多页)。"""
    sub = await session.get(Subscription, subscription_id)
    if sub is None:
        return [], False

    exclude_ids = exclude_ids or set()
    existing_titles = existing_titles or []
    # 从 DB 加载已有标题用于去重
    if not existing_titles:
        stmt = select(Gallery.normalized_title).where(Gallery.source_key == source.key)
        db_titles = [row[0] for row in (await session.execute(stmt)).fetchall()]
        existing_titles.extend(db_titles)
    all_new: list[GallerySummary] = []
    has_more = False

    for page_offset in range(max_search_pages):
        page = start_page + page_offset
        result = await source.search(sub.query, page=page, sort=sub.sort)
        if not result.items:
            break

        # 排掉 exclude_ids
        raw_items = [g for g in result.items if g.native_id not in exclude_ids]
        if not raw_items:
            has_more = bool(result.next_url or (result.total_pages > page + 1))
            continue

        # 查询 DB 中去重
        ids = [f"{source.key}:{item.native_id}" for item in raw_items]
        stmt = select(Gallery.id).where(Gallery.id.in_(ids))
        db_existing = {row[0] for row in (await session.execute(stmt)).fetchall()}
        new = [g for g in raw_items if f"{source.key}:{g.native_id}" not in db_existing]

        # 标题去重：排除与 existing_titles 相似的
        from comicfeed.cbz import normalize_title
        from comicfeed.dedup import _similarity
        filtered = []
        for g in new:
            nt = normalize_title(g.title)
            if any(_similarity(nt, et) > 0.999 for et in existing_titles):
                continue
            filtered.append(g)
            existing_titles.append(nt)
        new = filtered

        # 批次内标题去重
        if len(new) > 1:
            from comicfeed.dedup import find_similar_groups, resolve_duplicates
            groups = find_similar_groups(new)
            if groups:
                all_keep: set[str] = {g.native_id for g in new}
                for group in groups:
                    candidates = [(g.native_id, g.page_count) for g in group]
                    keep = resolve_duplicates(candidates)
                    all_keep -= {g.native_id for g in group}
                    all_keep |= keep
                new = [g for g in new if g.native_id in all_keep]
                _log.info("去重: %d 组候选 → 保留 %d 个", len(groups), len(new))

        all_new.extend(new)
        for g in new:
            exclude_ids.add(g.native_id)

        # 判断是否还有更多页
        has_more = bool(result.next_url or (result.total_pages > page + 1))
        if not has_more:
            break

    # 仅在首次非追加检查时更新时间
    if start_page <= 1:
        sub.last_checked_at = datetime.now()
        await session.commit()

    _log.info("订阅 [%s] 检查完成: %d 个新画廊 (翻 %d 页, has_more=%s)", sub.name, len(all_new), max_search_pages, has_more)
    return all_new, has_more


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

