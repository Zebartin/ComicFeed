from fastapi import APIRouter
from pydantic import BaseModel

from comicfeed.infrastructure.config import get_setting, set_setting

router = APIRouter(prefix="/api/settings", tags=["settings"])

DEFAULTS = {
    "check_interval": "10",
    "download_path": "",
    "download_retry": "3",
    "proxy": "",
    "global_concurrency": "5",
    "komga_url": "",
    "komga_user": "",
    "komga_password": "",
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


class WebhookTest(BaseModel):
    url: str = ""


@router.post("/test-webhook")
async def test_webhook(data: WebhookTest | None = None):
    """发送测试 Webhook，优先用传入的值。"""
    url = (data.url if data and data.url else "") or (await get_setting("webhook_url", "") or "")
    if not url:
        return {"ok": False, "error": "未配置 Webhook URL"}
    import httpx
    from comicfeed.infrastructure.notifications import send_webhook
    try:
        await send_webhook(url, {"name": "test.webhook", "data": {"message": "ComicFeed 测试通知"}})
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


class KomgaTest(BaseModel):
    url: str = ""
    user: str = ""
    password: str = ""
    library_ids: str = ""


@router.post("/test-komga")
async def test_komga(data: KomgaTest | None = None):
    """测试 Komga 连接，优先用传入的值。"""
    async def _v(key, d=""):
        return (getattr(data, key, "") if data else "") or (await get_setting(f"komga_{key}" if key != "library_ids" else "komga_library_id", d) or d)

    base_url = (await _v("url")).rstrip("/") if await _v("url") else ""
    user = await _v("user")
    password = await _v("password")
    lib_ids_raw = await _v("library_ids")
    if not base_url:
        return {"ok": False, "error": "未配置 Komga URL"}
    if not lib_ids_raw:
        return {"ok": False, "error": "未配置 Library ID"}
    import base64
    import httpx
    headers = {}
    if user:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{base_url}/api/v1/libraries", headers=headers)
            if r.status_code == 401:
                return {"ok": False, "error": "认证失败，检查用户名密码"}
            r.raise_for_status()
            existing = {l["id"] for l in r.json()}
            configured = [lid.strip() for lid in lib_ids_raw.split(",") if lid.strip()]
            missing = [lid for lid in configured if lid not in existing]
            found = [lid for lid in configured if lid in existing]
            if missing and not found:
                return {"ok": False, "error": f"库 {', '.join(missing)} 不存在"}
            if missing:
                return {"ok": True, "warning": f"部分库不存在: {', '.join(missing)}。有效的: {', '.join(found)}"}
            return {"ok": True, "message": f"全部 {len(found)} 个库验证通过"}
    except httpx.ConnectError:
        return {"ok": False, "error": "无法连接 Komga 服务器"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


class EmailTest(BaseModel):
    host: str = ""
    port: int = 587
    user: str = ""
    password: str = ""
    to: str = ""


@router.post("/test-email")
async def test_email(data: EmailTest | None = None):
    """发送测试邮件，优先用传入的值。"""
    async def _v(key, default):
        return (getattr(data, key, "") if data else "") or (await get_setting(f"smtp_{key}", default) or default)

    host = await _v("host", "")
    if not host:
        return {"ok": False, "error": "未配置 SMTP 主机"}
    to = await _v("to", "")
    if not to:
        return {"ok": False, "error": "未配置收件人"}

    from comicfeed.infrastructure.notifications import send_email
    config = {
        "host": host,
        "port": int(await _v("port", "587")),
        "user": await _v("user", ""),
        "password": await _v("password", ""),
        "to": to,
    }
    try:
        await send_email(config, {"name": "test.email", "data": {"message": "ComicFeed 测试邮件"}})
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
