from fastapi import APIRouter

router = APIRouter(prefix="/api/queue", tags=["queue"])


def _get_tracker():
    from comicfeed.web.app import get_download_tracker
    return get_download_tracker()


@router.get("")
async def get_queue():
    tracker = _get_tracker()
    if tracker is None:
        return {"pending": [], "active": [], "completed": [], "failed": []}
    return tracker.snapshot()


@router.delete("/completed", status_code=204)
async def clear_completed():
    tracker = _get_tracker()
    if tracker:
        tracker.clear_completed()


@router.delete("/failed", status_code=204)
async def clear_failed():
    tracker = _get_tracker()
    if tracker:
        tracker.clear_failed()


@router.post("/retry/{gallery_id}")
async def retry_failed(gallery_id: str):
    tracker = _get_tracker()
    if tracker is None:
        return {"error": "tracker 不可用"}

    failed = [t for t in tracker.snapshot()["failed"] if t["gallery_id"] == gallery_id]
    if not failed:
        return {"error": "未找到失败任务"}
    kw = failed[0].get("retry_kwargs", {})
    if not kw:
        return {"error": "缺少重试参数"}

    from comicfeed.config import get_source_proxy, get_setting
    from comicfeed.credentials import get_source_credentials
    from comicfeed.web.app import get_source_manager
    from comicfeed.downloader import download_gallery
    import asyncio

    source_key = kw["source_key"]
    mgr = get_source_manager()
    creds = await get_source_credentials(source_key)
    proxy = await get_source_proxy(source_key)
    source = mgr.get_source(source_key, credentials=creds, proxy=proxy)
    if source is None:
        return {"error": f"源 {source_key} 不可用"}

    out_dir = kw.get("output_dir") or await get_setting("download_path", ".")
    gid = kw["gallery_id"]
    full_gid = f"{source_key}:{gid}"
    tracker.enqueue(full_gid, title=gid, total_pages=0, retry_kwargs=kw)

    async def _retry():
        try:
            await download_gallery(source, gid, out_dir, tracker=tracker, fire_events=False,
                                   gallery_url=kw.get("gallery_url", ""),
                                   append_pages=kw.get("append_pages", False),
                                   replaces_native_id=kw.get("replaces_native_id", ""),
                                   cbz_max_pages=kw.get("cbz_max_pages", 0))
        except Exception as e:
            tracker.failed(full_gid, str(e))
    asyncio.create_task(_retry())
    return {"status": "retrying", "gallery_id": full_gid}
