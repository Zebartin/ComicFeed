"""CBZ 打包：广告检测 + 分卷 + 增量追加。页面从磁盘缓存读取，不驻内存。"""
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from zipfile import ZipFile as _ZipFile

from comicfeed.io.cbz import make_cbz_name, pack_cbz
from comicfeed.io.detect_ad import detect_ads_from_tail
from comicfeed.io.page_fetcher import read_from_cache
from comicfeed.infrastructure.log import get

_log = get(__name__)


@dataclass
class AppendContext:
    old_pages: list[bytes]
    start_page: int
    vacancy: int
    old_cbz_paths: list[str]


def strip_ads(cache_dir: str, detail, total: int, tags: list[str]) -> tuple[int, list[str]]:
    """从缓存读尾部页做广告检测。返回 (移除数量, 更新后标签)。"""
    # 读尾部最多 20 页用于检测
    check_count = min(20, total)
    tail_pages = read_from_cache(cache_dir, detail, total - check_count, check_count)
    ad_count = detect_ads_from_tail(tail_pages)
    if ad_count > 0:
        _log.info("检测到 %d 页广告 (共 %d 页)", ad_count, total)
        tags = [t for t in tags if "extraneous" not in t.lower() and "外部广告" not in t]
    return min(ad_count, total), tags


def _read_comicinfo_number(cbz_path: str) -> str:
    """读取 CBZ 内 ComicInfo.xml 的 Number 字段。"""
    try:
        with _ZipFile(cbz_path, "r") as z:
            if "ComicInfo.xml" in z.namelist():
                root = ET.fromstring(z.read("ComicInfo.xml"))
                el = root.find("Number")
                if el is not None and el.text:
                    return el.text
    except Exception:
        pass
    return ""


def _read_newest_number(output_dir: str) -> int | None:
    """取目录下最新 CBZ 的 Number 整数值（按 mtime）。"""
    if not os.path.isdir(output_dir):
        return None
    newest: tuple[float, str] | None = None  # (mtime, path)
    try:
        for entry in os.scandir(output_dir):
            if entry.is_file() and entry.name.lower().endswith(".cbz"):
                mtime = entry.stat().st_mtime
                if newest is None or mtime > newest[0]:
                    newest = (mtime, entry.path)
    except OSError:
        return None
    if newest is None:
        return None
    num = _read_comicinfo_number(newest[1])
    try:
        return int(num)
    except (ValueError, TypeError):
        return None


def pack_cbz_volumes(cache_dir: str, detail, total: int, gallery_id: str, title: str,
                      output_dir: str, cbz_max_pages: int, do_split: bool,
                      append_ctx: AppendContext | None = None) -> list[str]:
    """从磁盘缓存读取页面，分卷打包 CBZ。"""

    # 合并卷使用旧 CBZ 的 Number；新建卷扫描目录取最大 Number + 1
    old_vol_number = ""
    next_vol = 1
    if append_ctx and append_ctx.old_cbz_paths and do_split:
        old_vol_number = _read_comicinfo_number(append_ctx.old_cbz_paths[0])
    if do_split:
        max_num = _read_newest_number(output_dir)
        next_vol = max(max_num, 0) + 1 if max_num else 1

    def _pack_vol(vol_pages, start_page, number=None):
        if not vol_pages:
            return None
        if number is None:
            number = str((start_page // cbz_max_pages) + 1) if do_split else gallery_id
        fname = make_cbz_name(gallery_id, title, start_page + 1,
                              start_page + len(vol_pages),
                              total_pages=0 if do_split else len(vol_pages))
        fpath = os.path.join(output_dir, fname)
        _log.debug("打包 CBZ: %s (%d 页)", os.path.basename(fpath), len(vol_pages))
        with open(fpath, "wb") as f:
            pack_cbz(f, fname, detail, vol_pages, start_page=start_page + 1, number=number)
        return fpath

    files = []
    idx = 0  # 当前已消费的新页面数
    page_offset = 0

    if append_ctx and append_ctx.old_pages:
        if do_split and append_ctx.vacancy > 0:
            fill = min(append_ctx.vacancy, total)
            pages = append_ctx.old_pages + read_from_cache(cache_dir, detail, 0, fill)
            fp = _pack_vol(pages, append_ctx.start_page, number=old_vol_number or None)
            if fp:
                files.append(fp)
            _log.debug("合并第一卷: old=%d fill=%d start=%d",
                       len(append_ctx.old_pages), fill, append_ctx.start_page + 1)
            idx = fill
            page_offset = append_ctx.start_page + len(append_ctx.old_pages) + fill
        else:
            pages = append_ctx.old_pages + read_from_cache(cache_dir, detail, 0, total)
            fp = _pack_vol(pages, 0, number=old_vol_number or None)
            if fp:
                files.append(fp)
            _log.debug("不分卷合并: old=%d new=%d", len(append_ctx.old_pages), total)
            idx = total
    elif append_ctx:
        page_offset = append_ctx.start_page

    while idx < total:
        vol_count = min(cbz_max_pages, total - idx)
        vol_pages = read_from_cache(cache_dir, detail, idx, vol_count)
        # 新建卷：取目录扫描的最大值递推；非分卷或无数据则按页位置计算
        vol_num = str(next_vol) if do_split else None
        if do_split:
            next_vol += 1
        fp = _pack_vol(vol_pages, page_offset, number=vol_num)
        if fp:
            files.append(fp)
        _log.debug("续卷: start=%d pages=%d", page_offset + 1, len(vol_pages))
        page_offset += len(vol_pages)
        idx += vol_count

    if append_ctx:
        for p in append_ctx.old_cbz_paths:
            try:
                os.remove(p)
            except OSError:
                pass

    return files
