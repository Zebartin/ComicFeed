import httpx

from comicfeed.config import get_setting
from comicfeed.hooks import bus, Event
from comicfeed.log import get

_log = get(__name__)


async def _call_komga_scan(event: Event):
    """调用 Komga API 扫描库（支持多个 Library ID，逗号分隔）。"""
    base_url = await get_setting("komga_url", "")
    library_ids_raw = await get_setting("komga_library_id", "")
    api_key = await get_setting("komga_api_key", "")

    if not base_url or not library_ids_raw:
        return

    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key

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
