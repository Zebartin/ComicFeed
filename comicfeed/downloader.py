import os
from dataclasses import dataclass, field

from comicfeed.cbz import make_cbz_name, normalize_title, pack_cbz
from comicfeed.sources.base import BaseSource


@dataclass
class DownloadResult:
    gallery_id: str
    files: list[str] = field(default_factory=list)


async def download_gallery(
    source: BaseSource,
    gallery_id: str,
    output_dir: str,
    cbz_max_pages: int = 0,
) -> DownloadResult:
    """下载完整画廊并打包为 CBZ。"""
    detail = await source.get_gallery(gallery_id)
    title = normalize_title(detail.title)
    total = detail.reported_pages
    if cbz_max_pages <= 0:
        cbz_max_pages = total

    result = DownloadResult(gallery_id=gallery_id)

    for vol_start in range(0, total, cbz_max_pages):
        vol_end = min(vol_start + cbz_max_pages, total)
        pages = await source.download_pages(gallery_id, slice(vol_start, vol_end))
        fname = make_cbz_name(gallery_id, title, vol_start + 1, vol_end)
        fpath = os.path.join(output_dir, fname)
        with open(fpath, "wb") as f:
            pack_cbz(f, fname, detail, pages, start_page=vol_start + 1)
        result.files.append(fpath)

    return result
