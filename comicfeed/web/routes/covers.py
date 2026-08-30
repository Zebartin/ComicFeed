"""封面代理：pixiv 图片服务器（i.pximg.net）要求 Referer 为 pixiv 域，浏览器直连 403。

仅放行 i.pximg.net 主机，供 WebUI 卡片/画廊封面显示使用。
"""

import time
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

router = APIRouter(prefix="/api", tags=["covers"])

_HEADERS = {
    "Referer": "https://www.pixiv.net",
    "User-Agent": "PixivIOSApp/7.19.1 (iOS 16.6; iPhone14,5)",
}

_cache: dict[str, tuple[float, str, bytes]] = {}
_TTL = 3600.0
_MAX = 200


async def _fetch_cover(url: str) -> tuple[str, bytes]:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                 headers=_HEADERS) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            raise HTTPException(502, f"封面获取失败: HTTP {resp.status_code}")
        return resp.headers.get("content-type", "image/jpeg"), resp.content


@router.get("/cover")
async def cover(url: str):
    if urlparse(url).hostname != "i.pximg.net":
        raise HTTPException(400, "仅支持 pixiv 封面")
    entry = _cache.get(url)
    if entry and time.time() - entry[0] < _TTL:
        _, ctype, data = entry
        return Response(content=data, media_type=ctype)
    try:
        ctype, data = await _fetch_cover(url)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502, "封面获取失败")
    _cache[url] = (time.time(), ctype, data)
    if len(_cache) > _MAX:
        oldest = min(_cache, key=lambda k: _cache[k][0])
        del _cache[oldest]
    return Response(content=data, media_type=ctype)
