"""通知服务：邮仸、Webhook、Komga 扫描的直接调用。"""
import asyncio

import httpx

from comicfeed.config import get_setting
from comicfeed.log import get
from comicfeed.notifications import build_payload, send_email, send_webhook

_log = get(__name__)


async def notify_batch(data: dict):
    """批量下载完成通知（邮件 + Webhook + Komga 扫描）。"""
    event = type("_Event", (), {"name": "gallery.created", "data": data})()

    # 邮件
    try:
        host = await get_setting("smtp_host", "")
        if host:
            config = {
                "host": host,
                "port": int(await get_setting("smtp_port", "587") or "587"),
                "user": await get_setting("smtp_user", "") or "",
                "password": await get_setting("smtp_password", "") or "",
                "to": await get_setting("smtp_to", "") or "",
            }
            if config["to"]:
                await send_email(config, event)
    except Exception:
        _log.exception("邮件通知失败")

    # Webhook
    try:
        url = await get_setting("webhook_url", "")
        if url:
            await send_webhook(url, event)
    except Exception:
        _log.exception("Webhook 通知失败")

    # Komga 扫描
    try:
        await _komga_scan()
    except Exception:
        _log.exception("Komga 扫描失败")


async def _komga_scan():
    base_url = await get_setting("komga_url", "")
    library_ids_raw = await get_setting("komga_library_id", "")
    user = await get_setting("komga_user", "") or ""
    password = await get_setting("komga_password", "") or ""
    if not base_url or not library_ids_raw:
        return

    import base64
    headers = {}
    if user:
        headers["Authorization"] = "Basic " + base64.b64encode(
            f"{user}:{password}".encode()
        ).decode()

    base = base_url.rstrip("/")
    for lid in library_ids_raw.split(","):
        lid = lid.strip()
        if not lid:
            continue
        _log.info("触发 Komga 扫描: library=%s", lid)
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(f"{base}/api/v1/libraries/{lid}/scan", headers=headers)


async def notify_source_error(data: dict):
    """源错误通知。"""
    event = type("_Event", (), {"name": "source.error", "data": data})()

    # Webhook
    try:
        url = await get_setting("webhook_url", "")
        if url:
            await send_webhook(url, event)
    except Exception:
        _log.exception("Webhook 通知失败")
