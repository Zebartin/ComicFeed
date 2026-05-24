from fastapi import APIRouter

from comicfeed.source_manager import SourceManager

router = APIRouter(prefix="/api/sources", tags=["sources"])


def _get_manager() -> "SourceManager":
    from comicfeed.web.app import get_source_manager
    return get_source_manager()


@router.get("")
async def list_sources():
    mgr = _get_manager()
    return [
        {"key": s.key, "name": s.name, "version": s.version,
         "domains": s.domains, "auth_schema": s.auth_schema.name}
        for s in mgr.list_sources()
    ]
