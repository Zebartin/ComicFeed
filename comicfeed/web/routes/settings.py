from fastapi import APIRouter

from comicfeed.config import get_setting, set_setting

router = APIRouter(prefix="/api/settings", tags=["settings"])

DEFAULTS = {
    "check_interval": "10",
    "download_path": "",
    "proxy": "",
    "global_concurrency": "5",
    "komga_url": "",
    "komga_api_key": "",
    "komga_library_id": "",
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_user": "",
    "smtp_password": "",
    "smtp_to": "",
    "webhook_url": "",
    "auth_username": "admin",
    "auth_password": "",
}


@router.get("")
async def list_settings():
    result = {}
    for key, default in DEFAULTS.items():
        result[key] = await get_setting(key, default)
    return result


@router.put("/{key}")
async def update_setting(key: str, value: str = ""):
    await set_setting(key, value)
    return {"key": key, "value": value}


@router.post("/test-webhook")
async def test_webhook():
    """发送测试 Webhook。"""
    url = await get_setting("webhook_url", "")
    if not url:
        return {"ok": False, "error": "未配置 Webhook URL"}
    import httpx
    from comicfeed.hooks import Event
    from comicfeed.notifications import send_webhook
    try:
        await send_webhook(url, Event("test.webhook", {"message": "ComicFeed 测试通知"}))
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/test-email")
async def test_email():
    """发送测试邮件。"""
    host = await get_setting("smtp_host", "")
    if not host:
        return {"ok": False, "error": "未配置 SMTP 主机"}
    from comicfeed.hooks import Event
    from comicfeed.notifications import send_email
    config = {
        "host": host,
        "port": int(await get_setting("smtp_port", "587") or "587"),
        "user": await get_setting("smtp_user", "") or "",
        "password": await get_setting("smtp_password", "") or "",
        "to": await get_setting("smtp_to", "") or "",
    }
    if not config["to"]:
        return {"ok": False, "error": "未配置收件人"}
    try:
        await send_email(config, Event("test.email", {"message": "ComicFeed 测试邮件"}))
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
