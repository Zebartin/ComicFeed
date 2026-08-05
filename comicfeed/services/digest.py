"""下载摘要 (digest)：按 cron 定时聚合 DownloadEvent，分组发送。

last_digest_at 记录上次成功消费点；无新事件则跳过；至少一个通道成功才推进。
"""
from datetime import datetime, timedelta

from comicfeed.infrastructure.config import get_setting, set_setting
from comicfeed.infrastructure.log import get
from comicfeed.infrastructure.database import get_session
from comicfeed.infrastructure.notifications import send_digest_email, send_webhook
from comicfeed.repositories.download_event import delete_before, pending_since

_log = get(__name__)

EMAIL_ITEM_LIMIT = 12
WEBHOOK_ITEM_LIMIT = 5
FAILED_LIMIT = 5

_EPOCH = datetime(1970, 1, 1)


def _item(e) -> dict:
    return {"gallery_id": e.gallery_id, "title": e.title, "cover_url": e.cover_url,
            "web_url": e.web_url, "page_count": e.page_count}


def build_digest(events) -> dict | None:
    """将事件按订阅名分组。无事件返回 None（调用方跳过本次通知）。"""
    if not events:
        return None
    groups: dict[str, list] = {}
    for e in events:
        groups.setdefault(e.subscription_name, []).append(e)

    subscriptions = []
    total_count = 0
    total_failed = 0
    for name in sorted(groups):
        evs = groups[name]
        ok = [e for e in evs if e.status == "success"]
        fail = [e for e in evs if e.status == "failed"]
        total_count += len(ok)
        total_failed += len(fail)
        subscriptions.append({
            "name": name,
            "count": len(ok),
            "failed_count": len(fail),
            "items": [_item(e) for e in ok[:EMAIL_ITEM_LIMIT]],
            "failed": [{"title": f.title, "error": f.error} for f in fail[:FAILED_LIMIT]],
        })
    return {
        "subscriptions": subscriptions,
        "total_count": total_count,
        "total_failed": total_failed,
        "since": min(e.created_at for e in events),
        "until": max(e.created_at for e in events),
    }


def webhook_payload(digest: dict) -> dict:
    """webhook 负载：每订阅结果截断到 WEBHOOK_ITEM_LIMIT。"""
    subs = []
    for g in digest["subscriptions"]:
        subs.append({
            "name": g["name"],
            "count": g["count"],
            "failed_count": g["failed_count"],
            "items": g["items"][:WEBHOOK_ITEM_LIMIT],
            "failed": g["failed"],
        })
    return {
        "since": digest["since"].isoformat(),
        "until": digest["until"].isoformat(),
        "total_count": digest["total_count"],
        "total_failed": digest["total_failed"],
        "subscriptions": subs,
    }


async def _smtp_config() -> dict | None:
    host = await get_setting("smtp_host", "")
    to = await get_setting("smtp_to", "") or ""
    if not host or not to:
        return None
    return {
        "host": host,
        "port": int(await get_setting("smtp_port", "587") or "587"),
        "user": await get_setting("smtp_user", "") or "",
        "password": await get_setting("smtp_password", "") or "",
        "to": to,
    }


async def send_digest() -> bool:
    """聚合上次通知以来的下载事件并发送摘要。返回 True 表示发送过。"""
    since_raw = await get_setting("last_digest_at", "") or ""
    try:
        since = datetime.fromisoformat(since_raw)
    except ValueError:
        since = _EPOCH

    async with get_session() as session:
        events = await pending_since(session, since)
    digest = build_digest(events)
    if digest is None:
        _log.info("摘要跳过: 无新下载事件")
        return False

    sent = False
    try:
        cfg = await _smtp_config()
        if cfg:
            await send_digest_email(cfg, digest)
            sent = True
    except Exception:
        _log.exception("摘要邮件发送失败")

    try:
        url = await get_setting("webhook_url", "") or ""
        if url:
            await send_webhook(url, {"name": "digest", "data": webhook_payload(digest)})
            sent = True
    except Exception:
        _log.exception("摘要 Webhook 发送失败")

    if sent:
        # 推进到已消费事件的最大时间（而非发送时刻），避免并发完成的下载被永久跳过
        await set_setting("last_digest_at", digest["until"].isoformat())
        _log.info("摘要已发送: %d 订阅 %d 成功 %d 失败",
                  len(digest["subscriptions"]), digest["total_count"], digest["total_failed"])
    else:
        _log.warning("摘要发送失败，last_digest_at 保持原值，下次重试")
    return sent


async def cleanup_download_events(retention_days: int = 60) -> int:
    """删除已消费（≤ last_digest_at）或超过保留期的下载事件。每周由调度器调用。"""
    last_raw = (await get_setting("last_digest_at", "")) or ""
    last_digest_at = _EPOCH
    if last_raw:
        try:
            last_digest_at = datetime.fromisoformat(last_raw)
        except ValueError:
            last_digest_at = _EPOCH
    cutoff = max(last_digest_at, datetime.now() - timedelta(days=retention_days))
    async with get_session() as session:
        deleted = await delete_before(session, cutoff)
        await session.commit()
    if deleted:
        _log.info("清理下载事件: 删除 %d 条", deleted)
    return deleted
