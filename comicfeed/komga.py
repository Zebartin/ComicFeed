import httpx

from comicfeed.config import get_setting
from comicfeed.hooks import bus, Event
from comicfeed.log import get

_log = get(__name__)


async def _call_komga_scan(event: Event):
    """调用 Komga API 扫描库。"""
    base_url = await get_setting("komga_url", "")
    library_id = await get_setting("komga_library_id", "")
    api_key = await get_setting("komga_api_key", "")

    if not base_url or not library_id:
        return

    _log.info("触发 Komga 扫描: library=%s", library_id)
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key

    url = f"{base_url.rstrip('/')}/api/v1/libraries/{library_id}/scan"
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(url, headers=headers)


def register_komga_hook():
    """注册 Komga 扫描钩子。"""
    bus.on("gallery.created", _call_komga_scan)
    bus.on("gallery.updated", _call_komga_scan)
