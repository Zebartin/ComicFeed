"""逐页下载 + 磁盘缓存。重试由 source.download_pages 内部处理。"""
import os
import shutil
import time
from contextlib import contextmanager

from comicfeed.infrastructure.log import get

_log = get(__name__)

_CACHE_TTL = 259200  # 72h
_CACHE_MAX_MB = 500
_CHUNK_SIZE = 10  # 单次 download_pages 请求的页数上限（限制峰值内存）
# 源在块内逐页下载时通过 on_page 回调逐页上报进度，避免 UI 进度每 10 页才跳一次
_active_caches: dict[str, int] = {}


@contextmanager
def protect_cache(cache_dir: str):
    """下载到打包结束期间，保护缓存不被其他任务淘汰。"""
    path = os.path.normcase(os.path.abspath(cache_dir))
    _active_caches[path] = _active_caches.get(path, 0) + 1
    try:
        yield
    finally:
        _active_caches[path] -= 1
        if not _active_caches[path]:
            del _active_caches[path]


def cleanup_cache(root: str):
    """删除空闲缓存中的过期文件，超大小阈值时淘汰最旧。"""
    if not os.path.exists(root):
        return
    now = time.time()
    total = 0
    keep = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name for name in dirnames
            if os.path.normcase(os.path.abspath(os.path.join(dirpath, name))) not in _active_caches
        ]
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


def _contiguous_runs(indices: list[int]) -> list[tuple[int, int]]:
    """将升序缺失索引合并为连续区间 [(start, end), ...]（含端点）。"""
    if not indices:
        return []
    runs = []
    start = prev = indices[0]
    for i in indices[1:]:
        if i == prev + 1:
            prev = i
        else:
            runs.append((start, prev))
            start = prev = i
    runs.append((start, prev))
    return runs


async def fetch_pages(source, gallery_id: str, gallery_url: str, detail,
                       total: int, cache_dir: str, tracker=None,
                       full_gid: str = "") -> int:
    """分块下载页面到磁盘缓存。返回已下载数量。

    每块（≤ _CHUNK_SIZE 页）调一次 source.download_pages，源内部对整块
    复用同一个 HTTP client 并逐页串行，重试也由源内部完成（页失败即画廊放弃）。
    源每下载完一页即回调 on_page，队列进度随之逐页刷新。
    """
    downloaded = 0
    last_reported = 0

    def _report(value: int):
        # 进度只增不减：回调可能比写盘先报出同一页，避免进度条回跳
        nonlocal last_reported
        if value <= last_reported:
            return
        last_reported = value
        if tracker:
            tracker.progress(full_gid, value)

    for chunk_start in range(0, total, _CHUNK_SIZE):
        chunk_end = min(chunk_start + _CHUNK_SIZE, total)
        missing = []
        for abs_idx in range(chunk_start, chunk_end):
            pid = detail.page_native_ids[abs_idx] if abs_idx < len(detail.page_native_ids) else ""
            cache_name = (pid + ".dat") if pid else f"{abs_idx:04d}.dat"
            cache_file = os.path.join(cache_dir, cache_name)
            if os.path.exists(cache_file) and os.path.getsize(cache_file) > 0:
                downloaded += 1
                _report(downloaded)
            else:
                missing.append(abs_idx)
        if not missing:
            continue
        # 缺失页通常为整块连续；部分失败重试时拆成连续区间请求，避免重复下载已缓存页
        for start, end in _contiguous_runs(missing):
            done_in_run = 0

            def on_page():
                # 源每下载完一页立即上报，进度逐页刷新而非整块完成后跳变
                nonlocal done_in_run
                done_in_run += 1
                _report(downloaded + done_in_run)

            chunk = await source.download_pages(
                gallery_id, slice(start, end + 1), gallery_url=gallery_url, detail=detail,
                on_page=on_page,
            )
            for i, data in enumerate(chunk, start):
                pid = detail.page_native_ids[i] if i < len(detail.page_native_ids) else ""
                cache_name = (pid + ".dat") if pid else f"{i:04d}.dat"
                with open(os.path.join(cache_dir, cache_name), "wb") as f:
                    f.write(data)
                downloaded += 1
                _report(downloaded)
    return downloaded


def read_from_cache(cache_dir: str, detail, start: int, count: int) -> list[bytes]:
    """从磁盘缓存读取指定范围的页面。"""
    pages = []
    for abs_idx in range(start, start + count):
        pid = detail.page_native_ids[abs_idx] if abs_idx < len(detail.page_native_ids) else ""
        cache_name = (pid + ".dat") if pid else f"{abs_idx:04d}.dat"
        cache_file = os.path.join(cache_dir, cache_name)
        if os.path.exists(cache_file):
            with open(cache_file, "rb") as f:
                data = f.read()
            if not data:
                raise ValueError(f"页面缓存为空: {cache_file}")
            pages.append(data)
        else:
            raise FileNotFoundError(f"页面缓存缺失: {cache_file}")
    return pages
