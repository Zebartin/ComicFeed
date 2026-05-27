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
