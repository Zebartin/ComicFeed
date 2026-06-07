"""逐页下载 + 磁盘缓存 + 重试。"""
import asyncio
import os
import shutil
import time

from comicfeed.infrastructure.config import get_setting as _cfg
from comicfeed.infrastructure.log import get

_log = get(__name__)

_CACHE_TTL = 259200  # 72h
_CACHE_MAX_MB = 500


def cleanup_cache(root: str):
    """删除过期缓存文件，超总大小阈值时淘汰最旧。"""
    if not os.path.exists(root):
        return
    now = time.time()
    total = 0
    keep = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            if now - st.st_mtime > _CACHE_TTL:
                try:
                    os.remove(fp)
                except OSError:
                    pass
            else:
                total += st.st_size
                keep.append((st.st_mtime, fp))
    if total > _CACHE_MAX_MB * 1024 * 1024:
        keep.sort()
        for _, fp in keep:
            try:
                st = os.stat(fp)
                os.remove(fp)
                total -= st.st_size
            except OSError:
                pass
            if total <= _CACHE_MAX_MB * 1024 * 1024:
                break


async def fetch_pages(source, gallery_id: str, gallery_url: str, detail,
                       total: int, cache_dir: str, tracker=None,
                       full_gid: str = "") -> int:
    """逐页下载到磁盘缓存。返回已下载数量。"""
    try:
        retry_count = int((await _cfg("download_retry", "3")) or "3")
    except Exception:
        retry_count = 3

    downloaded = 0
    for abs_idx in range(0, total):
        pid = detail.page_native_ids[abs_idx] if abs_idx < len(detail.page_native_ids) else ""
        cache_name = (pid + ".dat") if pid else f"{abs_idx:04d}.dat"
        cache_file = os.path.join(cache_dir, cache_name)
        if os.path.exists(cache_file):
            downloaded += 1
            _log.debug("缓存命中: %s page=%d pid=%s", gallery_id, abs_idx + 1, pid)
            if tracker:
                tracker.progress(full_gid, downloaded)
            continue
        for retry in range(retry_count):
            try:
                chunk = await source.download_pages(gallery_id, slice(abs_idx, abs_idx + 1),
                                                     gallery_url=gallery_url, detail=detail)
                data = chunk[0]
                with open(cache_file, "wb") as f:
                    f.write(data)
                downloaded += 1
                if tracker:
                    tracker.progress(full_gid, downloaded)
                break
            except Exception as e:
                if retry < retry_count - 1:
                    _log.warning("下载失败(重试%d/%d): %s page=%d - %r",
                                 retry + 1, retry_count, gallery_id, abs_idx + 1, e)
                    await asyncio.sleep(3)
                else:
                    _log.error("下载失败: %s page=%d - %r", gallery_id, abs_idx + 1, e)
                    raise
    return downloaded


def read_from_cache(cache_dir: str, detail, start: int, count: int) -> list[bytes]:
    """从磁盘缓存读取指定范围的页面。"""
    pages = []
    for abs_idx in range(start, start + count):
        pid = detail.page_native_ids[abs_idx] if abs_idx < len(detail.page_native_ids) else ""
        cache_name = (pid + ".dat") if pid else f"{abs_idx:04d}.dat"
        cache_file = os.path.join(cache_dir, cache_name)
        if os.path.exists(cache_file):
            pages.append(open(cache_file, "rb").read())
        else:
            pages.append(b"")
    return pages
