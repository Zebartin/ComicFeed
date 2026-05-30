import asyncio
import glob
import os
import shutil
import time
from dataclasses import dataclass, field

from comicfeed.cbz import make_cbz_name, normalize_title, pack_cbz, read_cbz_pages
from comicfeed.log import get
from comicfeed.sources.base import BaseSource, GalleryDetail

_log = get(__name__)

_CACHE_TTL = 86400  # 24h
_CACHE_MAX_MB = 500


def _cleanup_cache(root: str):
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


@dataclass
class DownloadResult:
    gallery_id: str
    files: list[str] = field(default_factory=list)
    title: str = ""
    cover_url: str = ""
    web_url: str = ""
    page_count: int = 0


async def download_gallery(
    source: BaseSource,
    gallery_id: str,
    output_dir: str,
    cbz_max_pages: int = 0,
    tracker: "DownloadTracker | None" = None,
    fire_events: bool = True,
    save_to_db: bool = True,
    gallery_url: str = "",
    detail: GalleryDetail | None = None,
    append_pages: bool = False,
    replaces_native_id: str = "",
) -> DownloadResult:
    """下载完整画廊并打包为 CBZ。fire_events=False 时不触发事件。

    detail: 已预取的 GalleryDetail（增量更新时仅含新页面），跳过 get_gallery。
    append_pages: True 时只 INSERT 新 page 记录，不删旧（增量更新用）。
    replaces_native_id: 增量时被替换的旧画廊 native_id（用于查找已有 CBZ）。
    """
    from comicfeed.hooks import Event, bus

    os.makedirs(output_dir, exist_ok=True)

    if detail is None:
        _log.debug("get_gallery: %s url=%s", gallery_id, gallery_url)
        detail = await source.get_gallery(gallery_id, gallery_url=gallery_url)
    else:
        _log.debug("使用预取 detail: %s (%d 页)", gallery_id, detail.reported_pages)
    title = normalize_title(detail.title)
    total = detail.reported_pages
    _do_split = cbz_max_pages > 0
    if cbz_max_pages <= 0:
        cbz_max_pages = total

    full_gid = f"{source.key}:{gallery_id}"
    _log.debug("参数: full_gid=%s cbz_max_pages=%d do_split=%s total=%d append=%s replaces=%s",
               full_gid, cbz_max_pages, _do_split, total, append_pages, replaces_native_id)
    if tracker:
        tracker.started(full_gid, title, total, cover_url=detail.cover_url, web_url=detail.web_url)

    result = DownloadResult(gallery_id=full_gid, title=detail.title,
                            cover_url=detail.cover_url, web_url=detail.web_url,
                            page_count=total)
    downloaded = 0

    # 下载缓存
    _cache_root = os.path.join(os.getcwd(), ".cache")
    _cleanup_cache(_cache_root)
    _cache_dir = os.path.join(_cache_root, gallery_id)
    os.makedirs(_cache_dir, exist_ok=True)

    # 增量更新：准备向已有 CBZ 追加
    _old_count = 0
    _append_pages: list[bytes] = []
    _append_start = 0
    _vacancy = 0
    _old_cbz: list[str] = []  # 下载成功后删除的旧 CBZ
    if append_pages:
        from comicfeed.database import get_session
        async with get_session() as s:
            from sqlalchemy import func, select as sa_select
            from comicfeed.models import Page as PageModel2
            lookup_gid = f"{source.key}:{replaces_native_id}" if replaces_native_id else full_gid
            _old_count = (await s.execute(
                sa_select(func.count()).where(PageModel2.gallery_id == lookup_gid)
            )).scalar() or 0
        _log.debug("增量模式: lookup_gid=%s old_count=%d", lookup_gid, _old_count)
        if _old_count > 0:
            lookup_id = replaces_native_id or gallery_id
            pattern = os.path.join(output_dir, f"[[]{lookup_id}[]]*.cbz")
            existing = sorted(glob.glob(pattern))
            _log.debug("查找已有 CBZ: pattern=%s found=%d", pattern, len(existing))
            if existing:
                if _do_split:
                    pages_in_last = _old_count % cbz_max_pages or cbz_max_pages
                    _vacancy = cbz_max_pages - pages_in_last if pages_in_last < cbz_max_pages else 0
                    _log.debug("分卷模式: old_count=%d pages_in_last=%d vacancy=%d cbz_max=%d",
                               _old_count, pages_in_last, _vacancy, cbz_max_pages)
                    if _vacancy > 0:
                        _log.debug("重打包最后一卷: %s (%d 页)", existing[-1], pages_in_last)
                        _append_pages = read_cbz_pages(existing[-1])
                        _append_start = _old_count - pages_in_last
                        _old_cbz.append(existing[-1])
                else:
                    _log.debug("不分卷: 读取 %s (%d 页)", existing[0], _old_count)
                    _append_pages = read_cbz_pages(existing[0])
                    _append_start = 0
                    _old_cbz.append(existing[0])

    # 逐页下载（带磁盘缓存）
    try:
        from comicfeed.config import get_setting as _cfg
        _chunk_retry = int((await _cfg("download_retry", "3")) or "3")
    except Exception:
        _chunk_retry = 3
    all_new_pages: list[bytes] = []
    for abs_idx in range(0, total):
        pid = detail.page_native_ids[abs_idx] if abs_idx < len(detail.page_native_ids) else ""
        cache_name = (pid + ".dat") if pid else f"{abs_idx:04d}.dat"
        cache_file = os.path.join(_cache_dir, cache_name)
        if os.path.exists(cache_file):
            data = open(cache_file, "rb").read()
            all_new_pages.append(data)
            downloaded += 1
            _log.debug("缓存命中: %s page=%d pid=%s", gallery_id, abs_idx + 1, pid)
            if tracker:
                tracker.progress(full_gid, downloaded)
            continue

        for retry in range(_chunk_retry):
            try:
                pages = await source.download_pages(gallery_id, slice(abs_idx, abs_idx + 1), gallery_url=gallery_url, detail=detail)
                data = pages[0]
                with open(cache_file, "wb") as f:
                    f.write(data)
                all_new_pages.append(data)
                downloaded += 1
                if tracker:
                    tracker.progress(full_gid, downloaded)
                break
            except Exception as e:
                if retry < _chunk_retry - 1:
                    _log.warning("下载失败(重试%d/%d): %s page=%d - %r", retry + 1, _chunk_retry, gallery_id, abs_idx + 1, e)
                    await asyncio.sleep(3)
                else:
                    _log.error("下载失败: %s page=%d - %r", gallery_id, abs_idx + 1, e)
                    raise

    # 广告页检测
    from comicfeed.detect_ad import detect_ads_from_tail
    ad_count = detect_ads_from_tail(all_new_pages)
    if ad_count > 0:
        _log.info("检测到 %d 页广告 (共 %d 页)", ad_count, len(all_new_pages))
        all_new_pages = all_new_pages[:-ad_count] if ad_count < len(all_new_pages) else all_new_pages
        downloaded -= ad_count
        detail.tags = [t for t in detail.tags if "extraneous" not in t.lower() and "外部广告" not in t]

    # 打包 CBZ
    def _pack_vol(pages, start_page):
        if not pages:
            return
        fname = make_cbz_name(gallery_id, title, start_page, start_page + len(pages) - 1,
                              total_pages=0 if _do_split else len(pages))
        fpath = os.path.join(output_dir, fname)
        _log.debug("打包 CBZ: %s (%d 页)", os.path.basename(fpath), len(pages))
        with open(fpath, "wb") as f:
            pack_cbz(f, fname, detail, pages, start_page=start_page)
        result.files.append(fpath)

    remaining = list(all_new_pages)
    page_offset = 0 if _append_pages else _old_count
    if _append_pages:
        if _do_split:
            fill = min(_vacancy, len(remaining))
            _pack_vol(_append_pages + remaining[:fill], _append_start + 1)
            _log.debug("合并第一卷: old=%d fill=%d start=%d", len(_append_pages), fill, _append_start + 1)
            remaining = remaining[fill:]
            page_offset = _append_start + len(_append_pages) + fill
        else:
            _pack_vol(_append_pages + remaining, 1)
            _log.debug("不分卷合并: old=%d new=%d", len(_append_pages), len(remaining))
            remaining = []

    while remaining:
        vol_pages = remaining[:cbz_max_pages]
        remaining = remaining[cbz_max_pages:]
        _pack_vol(vol_pages, page_offset + 1)
        _log.debug("续卷: start=%d pages=%d", page_offset + 1, len(vol_pages))
        page_offset += len(vol_pages)

    # 清理本 gallery 缓存 + 删除旧 CBZ
    shutil.rmtree(_cache_dir, ignore_errors=True)
    for p in _old_cbz:
        try:
            os.remove(p)
        except OSError:
            pass

    if tracker:
        tracker.finished(full_gid)

    _log.info("下载完成: %s (%d 页) → %s", full_gid, downloaded, os.path.basename(result.files[0]) if result.files else "")

    if fire_events:
        await bus.fire(Event("gallery.created", {
            "gallery_id": full_gid, "title": title, "files": result.files,
        }))

    # 写入数据库
    if save_to_db:
        try:
            from datetime import datetime
            from comicfeed.database import get_session
            from comicfeed.models import Gallery
            import json
            now = datetime.now()
            async with get_session() as session:
                g = await session.get(Gallery, full_gid)
                if g is None:
                    g = Gallery(id=full_gid, source_key=source.key, native_id=gallery_id,
                                normalized_title=title, display_title=title,
                                cover_url=detail.cover_url, web_url=detail.web_url,
                                tags=json.dumps(detail.tags, ensure_ascii=False),
                                num_favorites=detail.num_favorites,
                                reported_pages=total, actual_pages=downloaded,
                                downloaded_at=now)
                    session.add(g)
                else:
                    g.actual_pages = downloaded
                    g.reported_pages = total
                    g.cover_url = detail.cover_url
                    g.web_url = detail.web_url
                    g.tags = json.dumps(detail.tags, ensure_ascii=False)
                    g.num_favorites = detail.num_favorites
                    g.downloaded_at = now
                g.file_path = result.files[0] if result.files else None
                await session.commit()
        except Exception:
            _log.exception("写入 DB 失败: %s", full_gid)

    # 写入页面记录（必须在 Gallery 写入之后，FK 约束）
    if save_to_db and detail.page_native_ids:
        try:
            from comicfeed.models import Page as PageModel
            from sqlalchemy import delete, update as sqla_update
            async with get_session() as session:
                if not append_pages:
                    await session.execute(delete(PageModel).where(PageModel.gallery_id == full_gid))
                for pid in detail.page_native_ids:
                    session.add(PageModel(gallery_id=full_gid, page_native_id=pid))
                # newer version：迁移旧 Page 到新 gallery_id
                if replaces_native_id:
                    old_gid = f"{source.key}:{replaces_native_id}"
                    await session.execute(sqla_update(PageModel).where(PageModel.gallery_id == old_gid).values(gallery_id=full_gid))
                await session.commit()
        except Exception:
            _log.exception("写入页面记录失败: %s", full_gid)

    return result


class DownloadPool:
    """全局 worker 池 + 每源队列控制并发下载。"""

    def __init__(self, max_workers: int = 5):
        self._global_sem = asyncio.Semaphore(max_workers)
        self._source_limits: dict[str, asyncio.Semaphore] = {}

    def set_source_limit(self, source_key: str, max_slots: int):
        self._source_limits[source_key] = asyncio.Semaphore(max_slots)

    def _source_sem(self, source: BaseSource) -> asyncio.Semaphore | None:
        return self._source_limits.get(source.key)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def download(
        self,
        source: BaseSource,
        gallery_id: str,
        output_dir: str,
        cbz_max_pages: int = 0,
        tracker: "DownloadTracker | None" = None,
        fire_events: bool = True,
        save_to_db: bool = True,
        gallery_url: str = "",
        detail: GalleryDetail | None = None,
        append_pages: bool = False,
        replaces_native_id: str = "",
    ) -> DownloadResult:
        """获取全局和源级信号量后执行下载。"""
        src_sem = self._source_sem(source)
        async with self._global_sem:
            kwargs = dict(source=source, gallery_id=gallery_id, output_dir=output_dir,
                          cbz_max_pages=cbz_max_pages, tracker=tracker, fire_events=fire_events,
                          save_to_db=save_to_db, gallery_url=gallery_url,
                          detail=detail, append_pages=append_pages,
                          replaces_native_id=replaces_native_id)
            if src_sem:
                async with src_sem:
                    return await download_gallery(**kwargs)
            else:
                return await download_gallery(**kwargs)


class DownloadTracker:
    """下载队列追踪：pending → active → completed/failed。"""

    def __init__(self, keep_recent: int = 50):
        self._pending: list[dict] = []
        self._active: dict[str, dict] = {}
        self._completed: list[dict] = []
        self._failed: list[dict] = []
        self._keep = keep_recent

    def enqueue(self, gallery_id: str, title: str = "", total_pages: int = 0,
                cover_url: str = "", web_url: str = ""):
        """将下载加入待处理队列。"""
        task = {"gallery_id": gallery_id, "title": title, "total_pages": total_pages,
                "downloaded": 0, "cover_url": cover_url, "web_url": web_url,
                "status": "pending"}
        self._pending.append(task)

    def started(self, gallery_id: str, title: str, total_pages: int,
                cover_url: str = "", web_url: str = ""):
        """标记开始下载：从 pending 移动到 active。"""
        # 先从 pending 移除
        self._pending = [t for t in self._pending if t["gallery_id"] != gallery_id]
        task = {"gallery_id": gallery_id, "title": title, "total_pages": total_pages,
                "downloaded": 0, "cover_url": cover_url, "web_url": web_url,
                "status": "active"}
        self._active[gallery_id] = task

    def progress(self, gallery_id: str, downloaded: int):
        if gallery_id in self._active:
            self._active[gallery_id]["downloaded"] = downloaded

    def finished(self, gallery_id: str):
        task = self._active.pop(gallery_id, None)
        if task:
            task["status"] = "completed"
            self._completed.append(task)
            if len(self._completed) > self._keep:
                self._completed = self._completed[-self._keep:]

    def failed(self, gallery_id: str, error: str = ""):
        task = self._active.pop(gallery_id, None)
        if task is None:
            # 可能是从 pending 直接失败（还未开始下载）
            self._pending = [t for t in self._pending if t["gallery_id"] != gallery_id]
            task = {"gallery_id": gallery_id, "status": "failed", "error": error}
        task["status"] = "failed"
        task["error"] = error
        self._failed.append(task)
        if len(self._failed) > self._keep:
            self._failed = self._failed[-self._keep:]

    def clear_completed(self):
        self._completed.clear()

    def clear_failed(self):
        self._failed.clear()

    def snapshot(self) -> dict:
        return {
            "pending": list(self._pending),
            "active": list(self._active.values()),
            "completed": list(self._completed),
            "failed": list(self._failed),
        }
