"""CBZ 打包：广告检测 + 分卷 + 增量追加。"""
import os
from dataclasses import dataclass

from comicfeed.io.cbz import make_cbz_name, pack_cbz
from comicfeed.io.detect_ad import detect_ads_from_tail
from comicfeed.infrastructure.log import get

_log = get(__name__)


@dataclass
class AppendContext:
    """增量追加上下文（由调用方在下载前计算好）。"""
    old_pages: list[bytes]     # 从旧 CBZ 读出的页面
    start_page: int            # 合并卷的起始页码（0-based）
    vacancy: int               # 最后一卷空位（0 表示已满）
    old_cbz_paths: list[str]   # 成功后需删除的旧 CBZ 文件路径


def strip_ads(pages: list[bytes], tags: list[str]) -> tuple[list[bytes], int, list[str]]:
    """广告检测，返回 (去广告页面, 移除数量, 更新后的标签)。"""
    ad_count = detect_ads_from_tail(pages)
    if ad_count > 0:
        _log.info("检测到 %d 页广告 (共 %d 页)", ad_count, len(pages))
        pages = pages[:-ad_count] if ad_count < len(pages) else pages
        tags = [t for t in tags if "extraneous" not in t.lower() and "外部广告" not in t]
    return pages, ad_count, tags


def pack_cbz_volumes(pages: list[bytes], detail, gallery_id: str, title: str,
                      output_dir: str, cbz_max_pages: int, do_split: bool,
                      append_ctx: AppendContext | None = None) -> list[str]:
    """分卷打包 CBZ，返回生成的文件路径列表。支持增量追加。"""
    def _pack_vol(vol_pages, start_page):
        if not vol_pages:
            return None
        fname = make_cbz_name(gallery_id, title, start_page + 1,
                              start_page + len(vol_pages),
                              total_pages=0 if do_split else len(vol_pages))
        fpath = os.path.join(output_dir, fname)
        _log.debug("打包 CBZ: %s (%d 页)", os.path.basename(fpath), len(vol_pages))
        with open(fpath, "wb") as f:
            pack_cbz(f, fname, detail, vol_pages, start_page=start_page + 1)
        return fpath

    files = []
    remaining = list(pages)
    page_offset = 0

    if append_ctx and append_ctx.old_pages:
        if do_split and append_ctx.vacancy > 0:
            fill = min(append_ctx.vacancy, len(remaining))
            fp = _pack_vol(append_ctx.old_pages + remaining[:fill],
                           append_ctx.start_page)
            if fp:
                files.append(fp)
            _log.debug("合并第一卷: old=%d fill=%d start=%d",
                       len(append_ctx.old_pages), fill, append_ctx.start_page + 1)
            remaining = remaining[fill:]
            page_offset = append_ctx.start_page + len(append_ctx.old_pages) + fill
        else:
            fp = _pack_vol(append_ctx.old_pages + remaining, 0)
            if fp:
                files.append(fp)
            _log.debug("不分卷合并: old=%d new=%d",
                       len(append_ctx.old_pages), len(remaining))
            remaining = []
    elif append_ctx:
        page_offset = append_ctx.start_page

    while remaining:
        vol_pages = remaining[:cbz_max_pages]
        remaining = remaining[cbz_max_pages:]
        fp = _pack_vol(vol_pages, page_offset)
        if fp:
            files.append(fp)
        _log.debug("续卷: start=%d pages=%d", page_offset + 1, len(vol_pages))
        page_offset += len(vol_pages)

    # 删除旧 CBZ
    if append_ctx:
        for p in append_ctx.old_cbz_paths:
            try:
                os.remove(p)
            except OSError:
                pass

    return files
