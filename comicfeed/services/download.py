"""下载编排：DownloadPool + download_gallery + 批量下载 + 通知。"""
import asyncio
import glob
import os
import shutil
from dataclasses import dataclass, field

from comicfeed.infrastructure.database import get_session
from comicfeed.infrastructure.log import get
from comicfeed.io.cbz import read_cbz_pages
from comicfeed.io.cbz_builder import AppendContext, pack_cbz_volumes, strip_ads
from comicfeed.io.page_fetcher import cleanup_cache, fetch_pages
from comicfeed.repositories.gallery import get_or_create
from comicfeed.repositories.page import append_new, count_for_gallery, migrate_gallery, replace_all
from comicfeed.sources.base import BaseSource, GalleryDetail, GallerySummary

_log = get(__name__)


@dataclass
class DownloadResult:
    gallery_id: str
    files: list[str] = field(default_factory=list)
    title: str = ""
    cover_url: str = ""
    web_url: str = ""
    page_count: int = 0


@dataclass
class DownloadTask:
    source_key: str
    gallery_id: str
    output_dir: str
    gallery_url: str = ""
    cbz_max_pages: int = 0
    filter_rules: str = ""
    detail: GalleryDetail | None = None
    append_pages: bool = False
    replaces_native_id: str = ""
    subscription_id: int | None = None
    title: str = ""
    cover_url: str = ""
    page_count: int = 0
    new_page_ids: list[str] = field(default_factory=list)


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
        save_to_db: bool = True,
        gallery_url: str = "",
        detail: GalleryDetail | None = None,
        append_pages: bool = False,
        replaces_native_id: str = "",
        filter_rules: str = "",
    ) -> DownloadResult:
        """获取全局和源级信号量后执行下载。"""
        src_sem = self._source_sem(source)
        kwargs = dict(source=source, gallery_id=gallery_id, output_dir=output_dir,
                      cbz_max_pages=cbz_max_pages, tracker=tracker,
                      save_to_db=save_to_db, gallery_url=gallery_url,
                      detail=detail, append_pages=append_pages,
                      replaces_native_id=replaces_native_id,
                      filter_rules=filter_rules)
        async with self._global_sem:
            if src_sem:
                async with src_sem:
                    return await _download_gallery(**kwargs)
            else:
                return await _download_gallery(**kwargs)


async def _download_gallery(
    source: BaseSource,
    gallery_id: str,
    output_dir: str,
    cbz_max_pages: int = 0,
    tracker: "DownloadTracker | None" = None,
    save_to_db: bool = True,
    gallery_url: str = "",
    detail: GalleryDetail | None = None,
    append_pages: bool = False,
    replaces_native_id: str = "",
    filter_rules: str = "",
) -> DownloadResult:
    """下载完整画廊并打包为 CBZ。"""
    os.makedirs(output_dir, exist_ok=True)

    if detail is None:
        _log.debug("get_gallery: %s url=%s", gallery_id, gallery_url)
        detail = await source.get_gallery(gallery_id, gallery_url=gallery_url)
    else:
        _log.debug("使用预取 detail: %s (%d 页)", gallery_id, detail.reported_pages)

    title = detail.title
    total = detail.reported_pages

    # 下载阶段筛选（exhentai 等源搜到时缺少 num_favorites/upload_date）
    if filter_rules:
        from comicfeed.services.subscription import _matches_filter
        from json import loads as _jloads
        try:
            rules = _jloads(filter_rules)
        except Exception:
            rules = []
        if rules:
            gs = GallerySummary(native_id=gallery_id, title=title,
                                cover_url=detail.cover_url, web_url=detail.web_url,
                                page_count=total, num_favorites=detail.num_favorites,
                                upload_date=detail.upload_date)
            if not _matches_filter(gs, rules):
                _log.info("筛选跳过: %s (不符合条件)", full_gid)
                return result

    do_split = cbz_max_pages > 0
    if cbz_max_pages <= 0:
        cbz_max_pages = total

    full_gid = f"{source.key}:{gallery_id}"
    _log.debug("参数: full_gid=%s cbz_max_pages=%d do_split=%s total=%d append=%s replaces=%s",
               full_gid, cbz_max_pages, do_split, total, append_pages, replaces_native_id)
    if tracker:
        tracker.started(full_gid, title, total, cover_url=detail.cover_url, web_url=detail.web_url)

    result = DownloadResult(gallery_id=full_gid, title=detail.title,
                            cover_url=detail.cover_url, web_url=detail.web_url,
                            page_count=total)

    # 增量追加上下文
    old_count = 0
    append_ctx: AppendContext | None = None
    if append_pages:
        async with get_session() as s:
            lookup_gid = f"{source.key}:{replaces_native_id}" if replaces_native_id else full_gid
            old_count = await count_for_gallery(s, lookup_gid)
        _log.debug("增量模式: lookup_gid=%s old_count=%d", lookup_gid, old_count)
        if old_count > 0:
            lookup_id = replaces_native_id or gallery_id
            pattern = os.path.join(output_dir, f"[[]{lookup_id}[]]*.cbz")
            existing = sorted(glob.glob(pattern))
            _log.debug("查找已有 CBZ: pattern=%s found=%d", pattern, len(existing))
            if existing:
                if do_split:
                    pages_in_last = old_count % cbz_max_pages or cbz_max_pages
                    vacancy = cbz_max_pages - pages_in_last if pages_in_last < cbz_max_pages else 0
                    _log.debug("分卷模式: old_count=%d pages_in_last=%d vacancy=%d cbz_max=%d",
                               old_count, pages_in_last, vacancy, cbz_max_pages)
                    if vacancy > 0:
                        _log.debug("重打包最后一卷: %s (%d 页)", existing[-1], pages_in_last)
                        append_ctx = AppendContext(
                            old_pages=read_cbz_pages(existing[-1]),
                            start_page=old_count - pages_in_last,
                            vacancy=vacancy,
                            old_cbz_paths=[existing[-1]],
                        )
                else:
                    _log.debug("不分卷: 读取 %s (%d 页)", existing[0], old_count)
                    append_ctx = AppendContext(
                        old_pages=read_cbz_pages(existing[0]),
                        start_page=0, vacancy=0,
                        old_cbz_paths=[existing[0]],
                    )

    # 下载页面
    cache_root = os.path.join(os.getcwd(), ".cache")
    cleanup_cache(cache_root)
    cache_dir = os.path.join(cache_root, gallery_id)
    os.makedirs(cache_dir, exist_ok=True)

    all_new_pages, downloaded = await fetch_pages(
        source, gallery_id, gallery_url, detail, total, cache_dir, tracker, full_gid
    )

    # 广告检测
    all_new_pages, ad_count, detail.tags = strip_ads(all_new_pages, detail.tags)
    downloaded -= ad_count
    result.page_count = downloaded

    # 打包 CBZ
    result.files = pack_cbz_volumes(
        all_new_pages, detail, gallery_id, title, output_dir,
        cbz_max_pages, do_split, append_ctx
    )

    # 清理缓存
    shutil.rmtree(cache_dir, ignore_errors=True)

    if tracker:
        tracker.finished(full_gid)

    _log.info("下载完成: %s (%d 页) → %s", full_gid, downloaded,
              os.path.basename(result.files[0]) if result.files else "")

    # 写入数据库
    if save_to_db:
        try:
            async with get_session() as session:
                await get_or_create(session, full_gid, source.key, gallery_id,
                                    title, detail.cover_url, detail.web_url,
                                    detail.tags, detail.num_favorites,
                                    total, downloaded)
                await session.commit()
        except Exception:
            _log.exception("写入 DB 失败: %s", full_gid)

    if save_to_db and detail.page_native_ids:
        try:
            async with get_session() as session:
                if append_pages:
                    await append_new(session, full_gid, detail.page_native_ids)
                else:
                    await replace_all(session, full_gid, detail.page_native_ids)
                if replaces_native_id:
                    await migrate_gallery(session,
                                          f"{source.key}:{replaces_native_id}", full_gid)
                await session.commit()
        except Exception:
            _log.exception("写入页面记录失败: %s", full_gid)

    return result


# 兼容旧导入
download_gallery = _download_gallery


async def download_batch(
    source, pool, tracker, tasks: list[DownloadTask],
    subscription_name: str = "",
) -> tuple[list[dict], list[dict]]:
    """批量下载，返回 (成功列表, 失败列表)。pool 可为 None（直接调 _download_gallery）。"""

    for t in tasks:
        full_gid = f"{t.source_key}:{t.gallery_id}"
        tracker.enqueue(full_gid, title=t.title or t.gallery_id,
                        total_pages=t.page_count,
                        cover_url=t.cover_url, web_url=t.gallery_url,
                        retry_kwargs={
                            "source_key": t.source_key,
                            "gallery_id": t.gallery_id,
                            "output_dir": t.output_dir,
                            "cbz_max_pages": t.cbz_max_pages,
                            "gallery_url": t.gallery_url,
                            "append_pages": t.append_pages,
                            "replaces_native_id": t.replaces_native_id,
                            "subscription_id": t.subscription_id,
                        })

    downloaded = []
    failed = []
    for t in tasks:
        full_gid = f"{t.source_key}:{t.gallery_id}"
        try:
            _log.info("开始下载: %s (%s)", full_gid, t.title)
            if pool:
                result = await pool.download(
                    source, t.gallery_id, t.output_dir,
                    tracker=tracker,
                    gallery_url=t.gallery_url,
                    detail=t.detail,
                    append_pages=t.append_pages,
                    replaces_native_id=t.replaces_native_id,
                    cbz_max_pages=t.cbz_max_pages,
                    filter_rules=t.filter_rules,
                )
            else:
                result = await _download_gallery(
                    source, t.gallery_id, t.output_dir,
                    tracker=tracker,
                    gallery_url=t.gallery_url,
                    detail=t.detail,
                    append_pages=t.append_pages,
                    replaces_native_id=t.replaces_native_id,
                    cbz_max_pages=t.cbz_max_pages,
                    filter_rules=t.filter_rules,
                )
            downloaded.append({
                "gallery_id": full_gid,
                "title": result.title or t.title,
                "files": result.files,
                "cover_url": result.cover_url or t.cover_url,
                "web_url": result.web_url or t.gallery_url,
                "page_count": result.page_count or t.page_count,
            })
        except Exception as e:
            _log.error("下载失败: %s - %s", full_gid, e)
            tracker.failed(full_gid, str(e),
                           title=t.title, total_pages=t.page_count,
                           cover_url=t.cover_url, web_url=t.gallery_url)
            failed.append({
                "gallery_id": full_gid,
                "title": t.title,
                "error": str(e),
            })

    if downloaded or failed:
        from comicfeed.services.notification import notify_batch
        await notify_batch({
            "subscription": subscription_name or "手动下载",
            "galleries": downloaded,
            "count": len(downloaded),
            "failed": failed,
            "failed_count": len(failed),
        })

    return downloaded, failed
