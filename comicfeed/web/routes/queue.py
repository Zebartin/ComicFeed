from fastapi import APIRouter

router = APIRouter(prefix="/api/queue", tags=["queue"])


def _get_tracker():
    from comicfeed.web.app import get_download_tracker
    return get_download_tracker()


@router.get("")
async def get_queue():
    tracker = _get_tracker()
    if tracker is None:
        return {"active": []}
    return {"active": tracker.active()}
