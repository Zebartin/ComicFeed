from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from comicfeed.infrastructure.source_manager import SourceManager

router = APIRouter(prefix="/api/sources", tags=["sources"])


def _get_manager() -> "SourceManager":
    from comicfeed.web.app import get_source_manager
    return get_source_manager()


@router.get("")
async def list_sources():
    mgr = _get_manager()
    return [
        {"key": s.key, "name": s.name, "version": s.version,
         "domains": s.domains, "auth_schema": s.auth_schema.name,
         "config": s.get_config_schema(),
         "sort_options": s.get_sort_options()}
        for s in mgr.list_sources()
    ]


class TestRequest(BaseModel):
    credentials: dict[str, str] | None = None


@router.post("/{key}/test")
async def test_source(key: str, body: TestRequest | None = None):
    """对源执行连接测试。可选传入表单当前值（未保存）作为凭证。"""
    from comicfeed.infrastructure.config import get_source_credentials, get_source_proxy
    mgr = _get_manager()
    if mgr.get_source_cls(key) is None:
        raise HTTPException(status_code=404, detail="源不存在")
    creds = dict(body.credentials) if body and body.credentials else await get_source_credentials(key)
    proxy = await get_source_proxy(key)
    source = mgr.get_source(key, credentials=creds, proxy=proxy)
    ok, message = await source.test_connection()
    return {"ok": ok, "message": message}
