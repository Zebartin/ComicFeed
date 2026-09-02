"""CBZ 打包：广告检测 + 分卷 + 增量追加。页面从磁盘缓存读取，不驻内存。"""
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
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
    old_ids: list[str] = field(default_factory=list)  # 全部旧页 id（DB 页记录），供合并卷保留原像素名


_WORK_PAGE_RE = re.compile(r"^(.*)_p\d+$")


def _work_key(pid: str) -> str | None:
    """页 ID → 作品 key：12345_p3 → 12345；12345_webp → 12345；非作品形态返回 None。"""
    m = _WORK_PAGE_RE.match(pid)
    if m:
        return m.group(1)
    if pid.endswith("_webp"):
        return pid[:-5]
    return None


def _volume_boundary(ids: list[str], idx: int, cap: int) -> int:
    """按作品边界定卷页数：窗口内能完整容纳的作品整卷收纳；

    首个作品就超过上限（窗口即被它占满）→ 硬切 cap。
    """
    total = len(ids)
    if idx < 0:
        idx = 0  # 防御：负索引会从列表尾部取值甚至越界
    if not ids or idx >= total:
        return min(cap, total - idx)
    keys = [_work_key(p) for p in ids[idx:total]]
    if any(k is None for k in keys):
        return min(cap, total - idx)  # 页 ID 非作品形态 → 维持位置切分
    j = idx
    last_full = idx
    while j < total:
        k = j
        while k < total and _work_key(ids[k]) == _work_key(ids[j]):
            k += 1
        last_full = k
        j = k
        if last_full - idx > cap:
            return last_full - idx  # 作品边界优先：跨过上限的作品纳入后封卷
    return last_full - idx  # 已到末尾：全部作品纳入（长作品整卷）


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


def _read_comicinfo_tags(cbz_path: str) -> list[str]:
    """读取 CBZ 内 ComicInfo.xml 的 Tags 字段。"""
    try:
        with _ZipFile(cbz_path, "r") as z:
            if "ComicInfo.xml" in z.namelist():
                root = ET.fromstring(z.read("ComicInfo.xml"))
                el = root.find("Tags")
                if el is not None and el.text:
                    return [t.strip() for t in el.text.split(",") if t.strip()]
    except Exception:
        pass
    return []


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

    # 展示用 ID：detail.display_id 显式设置时用它（"" = 文件名/ComicInfo 省略 ID）
    display_gid = gallery_id if getattr(detail, "display_id", None) is None else detail.display_id

    # 合并卷使用旧 CBZ 的 Number 与旧标签；新建卷扫描目录取最大 Number + 1
    old_vol_number = ""
    old_tags: list[str] = []
    if append_ctx and append_ctx.old_cbz_paths:
        old_tags = _read_comicinfo_tags(append_ctx.old_cbz_paths[0])
    next_vol = 1
    if append_ctx and append_ctx.old_cbz_paths and do_split:
        old_vol_number = _read_comicinfo_number(append_ctx.old_cbz_paths[0])
    if do_split:
        max_num = _read_newest_number(output_dir)
        next_vol = max(max_num, 0) + 1 if max_num else 1

    def _pack_vol(vol_pages, start_page, number=None, base_tags=None):
        if not vol_pages:
            return None
        if number is None:
            number = str((start_page // cbz_max_pages) + 1) if do_split else display_gid
        old_n = (append_ctx.start_page + len(append_ctx.old_pages)) if (
            append_ctx is not None) else 0
        # 保留页名：按绝对页序逐页取 id；旧页（追加合并）无 id → 回退序号
        page_ids = None
        if getattr(detail, "keep_page_names", False):
            pids = detail.page_native_ids
            page_ids = []
            for j in range(len(vol_pages)):
                rel = start_page + j - old_n
                if rel >= 0:
                    page_ids.append(pids[rel] if 0 <= rel < len(pids) else "")
                elif append_ctx and 0 <= start_page + j < len(append_ctx.old_ids):
                    # 旧页：按绝对位置取 DB 记录的原像素名
                    page_ids.append(append_ctx.old_ids[start_page + j])
                else:
                    page_ids.append("")
        # 卷级标签：该卷页的标签并集；合并卷并入旧卷标签
        vol_tags = None
        if getattr(detail, "page_tags", None):
            tagset = set(base_tags or [])
            for j in range(len(vol_pages)):
                rel = start_page + j - old_n
                if 0 <= rel < len(detail.page_tags):
                    tagset.update(detail.page_tags[rel])
            vol_tags = sorted(t for t in tagset if t)
        fname = make_cbz_name(display_gid, title, start_page + 1,
                              start_page + len(vol_pages),
                              total_pages=0 if do_split else len(vol_pages))
        fpath = os.path.join(output_dir, fname)
        _log.debug("打包 CBZ: %s (%d 页)", os.path.basename(fpath), len(vol_pages))
        with open(fpath, "wb") as f:
            pack_cbz(f, fname, detail, vol_pages, start_page=start_page + 1, number=number,
                     page_ids=page_ids, tags=vol_tags)
        return fpath

    files = []
    idx = 0  # 当前已消费的新页面数
    page_offset = 0

    if append_ctx and append_ctx.old_pages:
        if do_split and append_ctx.vacancy > 0:
            # 合并填页尊重作品边界：整作品纳入，跨过空隙的作品允许塞入（与软上限策略一致）
            if getattr(detail, "keep_page_names", False) and detail.page_native_ids:
                fill = _volume_boundary(detail.page_native_ids, 0, append_ctx.vacancy)
            else:
                fill = min(append_ctx.vacancy, total)
            pages = append_ctx.old_pages + read_from_cache(cache_dir, detail, 0, fill)
            fp = _pack_vol(pages, append_ctx.start_page, number=old_vol_number or None,
                           base_tags=old_tags)
            if fp:
                files.append(fp)
            _log.debug("合并第一卷: old=%d fill=%d start=%d",
                       len(append_ctx.old_pages), fill, append_ctx.start_page + 1)
            idx = fill
            page_offset = append_ctx.start_page + len(append_ctx.old_pages) + fill
        else:
            pages = append_ctx.old_pages + read_from_cache(cache_dir, detail, 0, total)
            fp = _pack_vol(pages, 0, number=old_vol_number or None, base_tags=old_tags)
            if fp:
                files.append(fp)
            _log.debug("不分卷合并: old=%d new=%d", len(append_ctx.old_pages), total)
            idx = total
    elif append_ctx:
        page_offset = append_ctx.start_page

    old_n = (append_ctx.start_page + len(append_ctx.old_pages)) if (
        append_ctx is not None) else 0
    while idx < total:
        vol_count = min(cbz_max_pages, total - idx)
        if getattr(detail, "keep_page_names", False) and detail.page_native_ids:
            # idx 在追加模式下是「新页计数」（filtered detail 下标），无需再减 old_n
            vol_count = _volume_boundary(detail.page_native_ids, idx, vol_count)
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
        new_abs = {os.path.abspath(f) for f in files}
        for p in append_ctx.old_cbz_paths:
            if os.path.abspath(p) in new_abs:
                continue  # 新卷覆盖了旧路径（同名不分卷），不能删
            try:
                os.remove(p)
            except OSError:
                pass

    return files
