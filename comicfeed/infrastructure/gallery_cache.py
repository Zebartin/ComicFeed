"""Gallery detail 缓存层。跨 HTTP 请求共享，不归 source 管。"""
import time

from comicfeed.sources.base import GalleryDetail

# get_gallery 短期缓存（消除跨请求重复调用）
_cache: dict[str, tuple[float, GalleryDetail]] = {}
_CACHE_TTL = 3000

# check_updates 产生的过滤 detail（供 batch_download 一次性消费）
_update_cache: dict[str, tuple[float, GalleryDetail]] = {}


def cache_get(url: str) -> GalleryDetail | None:
    entry = _cache.get(url)
    if entry and time.time() - entry[0] < _CACHE_TTL:
        return entry[1]
    if entry:
        del _cache[url]
    return None


def cache_set(url: str, detail: GalleryDetail):
    _cache[url] = (time.time(), detail)
    if len(_cache) > 50:
        oldest = min(_cache, key=lambda k: _cache[k][0])
        del _cache[oldest]


def update_cache_get(gallery_id: str) -> GalleryDetail | None:
    entry = _update_cache.get(gallery_id)
    if entry and time.time() - entry[0] < _CACHE_TTL:
        del _update_cache[gallery_id]
        return entry[1]
    if entry:
        del _update_cache[gallery_id]
    return None


def update_cache_set(gallery_id: str, detail: GalleryDetail):
    _update_cache[gallery_id] = (time.time(), detail)
    if len(_update_cache) > 50:
        oldest = min(_update_cache, key=lambda k: _update_cache[k][0])
        del _update_cache[oldest]
