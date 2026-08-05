"""Komga 扫描触发：下载完成后独立调用，不随通知。"""
import base64

import httpx

from comicfeed.infrastructure.config import get_setting
from comicfeed.infrastructure.log import get

_log = get(__name__)


async def trigger_komga_scan():
    """触发所有配置的 Komga library 扫描。best-effort，失败仅记日志。"""
    try:
        base_url = await get_setting("komga_url", "")
        library_ids_raw = await get_setting("komga_library_id", "")
        user = await get_setting("komga_user", "") or ""
        password = await get_setting("komga_password", "") or ""
        if not base_url or not library_ids_raw:
            return

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
    except Exception:
        _log.exception("Komga 扫描失败")
