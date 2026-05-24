"""nhentai 源下载验证脚本

用法:
    先设置环境变量 NHENTAI_COOKIES，然后:
    uv run python _dl_test.py <gallery_id> [起始页] [结束页]

示例:
    uv run python _dl_test.py 325160          # 下载全部页
    uv run python _dl_test.py 325160 0 3      # 下载第 1-3 页
    uv run python _dl_test.py 325160 -3       # 下载最后 3 页
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

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

    if len(sys.argv) < 2:
        print("用法: uv run python _dl_test.py <gallery_id> [起始] [结束]")
        sys.exit(1)

    gallery_id = sys.argv[1]
    source = NhentaiSource(credentials=parse_cookies(raw))

    # 获取画廊信息
    detail = await source.get_gallery(gallery_id)
    print(f"标题: {detail.title}")
    print(f"标签: {', '.join(detail.tags[:10])}")
    print(f"总页数: {detail.reported_pages}")

    # 确定页码范围
    total = detail.reported_pages
    if len(sys.argv) == 2:
        start, end = 0, total  # 全部
    elif len(sys.argv) == 3 and sys.argv[2].startswith("-"):
        n = int(sys.argv[2])
        start, end = total + n, total  # 最后 n 页（n 为负）
    elif len(sys.argv) == 3:
        start, end = 0, int(sys.argv[2])
    else:
        start, end = int(sys.argv[2]), int(sys.argv[3])

    if start < 0:
        start = total + start
    if end <= 0:
        end = total + end

    end = min(end, total)
    start = max(0, start)
    print(f"下载范围: {start+1}-{end} (共 {end - start} 页)")

    # 下载
    out_dir = os.path.join(os.path.dirname(__file__), f"nhentai_{gallery_id}")
    os.makedirs(out_dir, exist_ok=True)

    pages = await source.download_pages(gallery_id, slice(start, end))
    for i, data in enumerate(pages):
        ext = "jpg"
        if data[:3] == b"\x89PN":
            ext = "png"
        elif data[:4] == b"RIFF":
            ext = "webp"
        elif data[:4] == b"GIF8":
            ext = "gif"
        fname = os.path.join(out_dir, f"{start + i + 1:04d}.{ext}")
        with open(fname, "wb") as f:
            f.write(data)
        print(f"  [{start + i + 1:04d}.{ext}] {len(data):,} bytes")

    print(f"\n完成，保存到 {out_dir}")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
