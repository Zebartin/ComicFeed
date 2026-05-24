"""nhentai 源下载验证脚本

用法:
    先设置环境变量 NHENTAI_COOKIES，然后:
    uv run python _dl_test.py <gallery_id> [起始页] [结束页] [--max-pages N]

示例:
    uv run python _dl_test.py 325160               # 下载全部页，打包为 CBZ
    uv run python _dl_test.py 325160 0 30           # 下载第 1-30 页
    uv run python _dl_test.py 325160 -3             # 下载最后 3 页
    uv run python _dl_test.py 325160 --max-pages 30 # 每 30 页分一卷
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from comicfeed.cbz import make_cbz_name, normalize_title, pack_cbz
from comicfeed.sources.nhentai import NhentaiSource


def parse_cookies(raw: str) -> dict:
    cookies = {}
    for part in raw.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


async def main():
    raw = os.environ.get("NHENTAI_COOKIES", "")
    if not raw:
        print("错误：请设置 NHENTAI_COOKIES 环境变量")
        sys.exit(1)

    # 解析参数
    args = sys.argv[1:]
    max_pages = 0  # 0 = 不分卷
    if "--max-pages" in args:
        idx = args.index("--max-pages")
        max_pages = int(args[idx + 1])
        args = args[:idx] + args[idx + 2:]

    if not args:
        print("用法: uv run python _dl_test.py <gallery_id> [起始] [结束] [--max-pages N]")
        sys.exit(1)

    gallery_id = args[0]
    source = NhentaiSource(credentials=parse_cookies(raw))

    # 获取画廊信息
    detail = await source.get_gallery(gallery_id)
    title = normalize_title(detail.title)
    print(f"标题: {detail.title}")
    print(f"归一化: {title}")
    print(f"标签: {', '.join(detail.tags[:10])}")
    print(f"总页数: {detail.reported_pages}")

    # 确定页码范围
    total = detail.reported_pages
    if len(args) == 1:
        start, end = 0, total
    elif len(args) == 2 and args[1].startswith("-"):
        n = int(args[1])
        start, end = total + n, total
    elif len(args) == 2:
        start, end = 0, int(args[1])
    else:
        start, end = int(args[1]), int(args[2])

    if start < 0:
        start = total + start
    if end <= 0:
        end = total + end
    end = min(end, total)
    start = max(0, start)

    # 分卷下载
    if max_pages <= 0:
        max_pages = end - start

    out_dir = os.getcwd()
    for vol_start in range(start, end, max_pages):
        vol_end = min(vol_start + max_pages, end)
        print(f"\n下载卷: {vol_start+1}-{vol_end} ({vol_end - vol_start} 页)")

        pages = await source.download_pages(gallery_id, slice(vol_start, vol_end))
        fname = make_cbz_name(gallery_id, title, vol_start + 1, vol_end, total_pages=total)
        fpath = os.path.join(out_dir, fname)

        with open(fpath, "wb") as f:
            pack_cbz(f, fname, detail, pages, start_page=vol_start + 1)

        size_mb = os.path.getsize(fpath) / (1024 * 1024)
        print(f"  保存: {fname} ({size_mb:.1f} MB)")

    print(f"\n完成，保存到 {out_dir}")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
