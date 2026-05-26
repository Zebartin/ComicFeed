import base64

import httpx

from comicfeed.config import get_setting
from comicfeed.hooks import bus, Event
from comicfeed.log import get

_log = get(__name__)


def _basic_auth_header(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


async def _call_komga_scan(event: Event):
    """调用 Komga API 扫描库（支持多个 Library ID，逗号分隔）。"""
    base_url = await get_setting("komga_url", "")
    library_ids_raw = await get_setting("komga_library_id", "")
    user = await get_setting("komga_user", "") or ""
    password = await get_setting("komga_password", "") or ""

    if not base_url or not library_ids_raw:
        return

    headers = {}
    if user:
        headers["Authorization"] = _basic_auth_header(user, password)

    base = base_url.rstrip("/")
    for lid in library_ids_raw.split(","):
        lid = lid.strip()
        if not lid:
            continue
        _log.info("触发 Komga 扫描: library=%s", lid)
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(f"{base}/api/v1/libraries/{lid}/scan", headers=headers)


def register_komga_hook():
    """注册 Komga 扫描钩子。"""
    bus.on("gallery.created", _call_komga_scan)
    bus.on("gallery.updated", _call_komga_scan)
