from fastapi import APIRouter

from comicfeed.config import get_setting

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/status")
async def setup_status():
    checks = {}

    # 下载路径
    dl = await get_setting("download_path", "")
    checks["download_path"] = bool(dl)

    # 源凭证（至少一个源配置了）
    from comicfeed.credentials import get_source_credentials
    from comicfeed.web.app import get_source_manager
    mgr = get_source_manager()
    has_creds = False
    sources = [s.key for s in mgr.list_sources()]
    for sk in sources:
        creds = await get_source_credentials(sk)
        if creds:
            has_creds = True
            break
    checks["source_credentials"] = has_creds
    checks["sources_available"] = len(sources) > 0

    # Komga
    komga_url = await get_setting("komga_url", "")
    checks["komga"] = bool(komga_url) and bool(await get_setting("komga_library_id", ""))

    # 通知
    wh = await get_setting("webhook_url", "")
    smtp = await get_setting("smtp_host", "")
    checks["notifications"] = bool(wh or smtp)

    # 代理
    proxy = await get_setting("proxy", "")
    checks["proxy"] = bool(proxy)

    all_done = all(checks.values())
    checks["all_done"] = all_done

    return checks
