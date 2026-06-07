"""Komga 书架清理工具：遍历已读书籍，逐个决定删除或转移。

用法:
  uv run python tools/komga_cleanup.py --series-id <ID> --target-dir <转移目录>
  uv run python tools/komga_cleanup.py --series-id <ID> --target-dir <转移目录> --komga-url <URL> --komga-user <user> --komga-pass <pass>

依赖: httpx, tkinter (Python 自带)
"""
import argparse
import asyncio
import json
import os
import re
import subprocess
import tkinter as tk
from tkinter import messagebox, simpledialog
from urllib.parse import urlencode

import httpx

# ── 预留接口：Komga 路径 → 实际文件路径 ──────────────────────────
# 在此函数中实现你的路径映射逻辑，返回实际 cbz 路径或 None（跳过该书）
def komga_path_to_real(komga_path: str) -> str | None:
    """将 Komga 返回的 filePath 转换为操作系统实际路径。

    例如 Komga 的 Docker 路径 /books/xxx.cbz → 宿主机路径 /mnt/data/xxx.cbz
    """
    # TODO: 在此实现你的路径映射
    return komga_path


# ── 预留接口：打开文件 ──────────────────────────────────────────
def open_file(path: str):
    """用系统默认程序打开文件。"""
    if os.name == "nt":
        os.startfile(path)
    elif os.name == "posix":
        subprocess.run(["xdg-open", path])


# ── Komga API ────────────────────────────────────────────────────

async def get_series_books(base_url: str, series_id: str, auth: str) -> list[dict]:
    """获取系列下所有已读且可用的 book。"""
    books = []
    page = 0
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            r = await client.get(
                f"{base_url}/api/v1/series/{series_id}/books",
                params={"page": page, "size": 100, "unpaged": "true"},
                headers={"Authorization": auth} if auth else {},
            )
            r.raise_for_status()
            data = r.json()
            content = data.get("content", [])
            if not content:
                break
            for b in content:
                progress = b.get("readProgress", {})
                if progress.get("completed") and b.get("filePath"):
                    books.append(b)
            if data.get("last"):
                break
            page += 1
    return books


async def get_book_detail(base_url: str, book_id: str, auth: str) -> dict:
    """获取 book 详情（含 metadata.links 外部链接）。"""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{base_url}/api/v1/books/{book_id}",
            headers={"Authorization": auth} if auth else {},
        )
        r.raise_for_status()
        return r.json()


async def get_nhentai_gallery(native_id: str) -> dict:
    """获取 nhentai 画廊详情，返回 API 响应 dict。"""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"https://nhentai.net/api/v2/galleries/{native_id}")
        r.raise_for_status()
        return r.json()


# ── 解析 ─────────────────────────────────────────────────────────

_NHENTAI_URL = re.compile(r"https?://nhentai\.net/g/(\d+)/?")

_BRACKET = re.compile(r"\[([^\]]+)\]")


def extract_nhentai_id(links: list[dict]) -> str | None:
    """从 book 的 metadata.links 中提取 nhentai gallery ID。"""
    for link in links:
        url = link.get("url", "")
        m = _NHENTAI_URL.search(url)
        if m:
            return m.group(1)
    return None


def extract_artist_group(gallery: dict) -> tuple[list[str], list[str]]:
    """从 nhentai gallery 数据中提取 artist 和 group 标签名。"""
    artists = []
    groups = []
    for tag in gallery.get("tags", []):
        t = tag.get("type", "")
        name = tag.get("name", "")
        if not name:
            continue
        if t == "artist":
            artists.append(name)
        elif t == "group":
            groups.append(name)
    return artists, groups


def extract_bracket_title(book_name: str) -> str:
    """从书名中提取第一对方括号内容，如 [Circle (Author)] Title → Circle (Author)。"""
    m = _BRACKET.search(book_name)
    return m.group(1) if m else ""


# ── UI ────────────────────────────────────────────────────────────

class BookDialog:
    """单本书的决策对话框。"""

    def __init__(self, root: tk.Tk, book: dict, real_path: str, target_dir: str):
        self.root = root
        self.book = book
        self.real_path = real_path
        self.target_dir = target_dir
        self.result: str | None = None  # "delete", "transfer", "skip"

        root.title("Komga 书架清理")
        root.geometry("500x400")

        name = book.get("name", book.get("metadata", {}).get("title", "?"))
        tk.Label(root, text=f"标题: {name}", wraplength=460,
                 font=("", 12, "bold")).pack(pady=10, padx=20, anchor="w")
        tk.Label(root, text=f"路径: {real_path}", wraplength=460,
                 fg="gray").pack(padx=20, anchor="w")

        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=15)
        tk.Button(btn_frame, text="删除", command=self._delete,
                  bg="#e74c3c", fg="white", width=12, height=2).pack(side="left", padx=10)
        tk.Button(btn_frame, text="转移", command=self._transfer,
                  bg="#3498db", fg="white", width=12, height=2).pack(side="left", padx=10)
        tk.Button(btn_frame, text="跳过", command=self._skip,
                  width=12, height=2).pack(side="left", padx=10)

        self.info_label = tk.Label(root, text="", wraplength=460)
        self.info_label.pack(pady=10, padx=20)

        self.url_frame = tk.Frame(root)
        self.url_frame.pack(pady=5)

        self._extract_info = ""
        self._clip_text = ""

    def set_nhentai_info(self, artists: list[str], groups: list[str]):
        """填充 nhentai 搜索结果，展示可选 URL。"""
        base = "https://nhentai.net/search/?"
        self.url_frame.destroy()
        self.url_frame = tk.Frame(self.root)
        self.url_frame.pack(pady=5)

        options = []
        if artists and groups:
            a = " ".join(f'artist:"{x}"' for x in artists)
            g = " ".join(f'group:"{x}"' for x in groups)
            options.append(("artist+group", f"{a} {g}", f"artist+group: {', '.join(artists+groups)}"))
        if artists:
            a = " ".join(f'artist:"{x}"' for x in artists)
            options.append(("artist", a, f"artist: {', '.join(artists)}"))
        if groups:
            g = " ".join(f'group:"{x}"' for x in groups)
            options.append(("group", g, f"group: {', '.join(groups)}"))

        if not options:
            tk.Label(self.url_frame, text="无 artist/group 标签", fg="gray").pack()
            return

        tk.Label(self.url_frame, text="选择搜索链接:", font=("", 10, "bold")).pack(anchor="w")
        self._clip_text = ""

        for key, query, label in options:
            full_url = f"{base}{urlencode({'q': query + ' language:chinese'})}"
            frame = tk.Frame(self.url_frame)
            frame.pack(anchor="w", pady=2)
            tk.Button(frame, text=label, command=lambda k=key, q=query, l=label: self._pick_url(full_url, q, l),
                      bg="#e8f4fd", relief="flat").pack(side="left")
            # 显示完整链接
            tk.Label(frame, text=full_url, fg="gray", font=("", 8), wraplength=400).pack(side="left", padx=8)

    def _pick_url(self, url: str, query: str, label: str):
        """用户挑选了一个 URL。"""
        bracket = self._extract_info
        text = f"作者 - {bracket}\n{query}" if bracket else query
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.info_label.config(text=f"已复制到剪切板:\n{text}")

    def _delete(self):
        self.result = "delete"
        self.root.quit()

    def _transfer(self):
        self.result = "transfer"
        self.root.quit()

    def _skip(self):
        self.result = "skip"
        self.root.quit()


# ── 主流程 ───────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Komga 书架清理工具")
    parser.add_argument("--series-id", required=True, help="Komga 系列 ID")
    parser.add_argument("--target-dir", default="./_transferred", help="转移目标目录")
    parser.add_argument("--komga-url", default="http://localhost:25600", help="Komga 地址")
    parser.add_argument("--komga-user", default="")
    parser.add_argument("--komga-pass", default="")
    args = parser.parse_args()

    base = args.komga_url.rstrip("/")
    auth = ""
    if args.komga_user:
        import base64
        auth = "Basic " + base64.b64encode(
            f"{args.komga_user}:{args.komga_pass}".encode()
        ).decode()

    # 1. 获取书籍列表
    print(f"正在获取系列 {args.series_id} 的已读书籍...")
    books = await get_series_books(base, args.series_id, auth)
    print(f"找到 {len(books)} 本已读书籍")

    os.makedirs(args.target_dir, exist_ok=True)
    transferred = []
    deleted = 0
    skipped = 0

    for i, book in enumerate(books):
        name = book.get("name", book.get("metadata", {}).get("title", "?"))
        komga_path = book.get("filePath", "")
        if not komga_path:
            print(f"\n[{i+1}/{len(books)}] {name} — 无文件路径，跳过")
            skipped += 1
            continue

        # i. 路径转换
        real_path = komga_path_to_real(komga_path)
        if not real_path:
            print(f"\n[{i+1}/{len(books)}] {name} — 路径转换失败，跳过")
            skipped += 1
            continue

        print(f"\n[{i+1}/{len(books)}] {name}")

        # ii. 打开 CBZ + 提问
        open_file(real_path)

        root = tk.Tk()
        dialog = BookDialog(root, book, real_path, args.target_dir)

        # v. 检查 nhentai 链接
        try:
            detail = await get_book_detail(base, book["id"], auth)
            links = detail.get("metadata", {}).get("links", [])
            nhentai_id = extract_nhentai_id(links)
            if nhentai_id:
                gallery = await get_nhentai_gallery(nhentai_id)
                artists, groups = extract_artist_group(gallery)
                bracket = extract_bracket_title(name)
                dialog._extract_info = bracket
                dialog.set_nhentai_info(artists, groups)
        except Exception as e:
            dialog.info_label.config(text=f"获取画廊信息失败: {e}")

        root.mainloop()
        try:
            root.destroy()
        except Exception:
            pass

        if dialog.result == "delete":
            os.remove(real_path)
            deleted += 1
            print(f"  已删除")
        elif dialog.result == "transfer":
            dest = os.path.join(args.target_dir, os.path.basename(real_path))
            os.rename(real_path, dest)
            transferred.append({"book": name, "from": real_path, "to": dest})
            print(f"  已转移到 {dest}")
        else:
            skipped += 1
            print(f"  已跳过")

    print(f"\n完成: 删除 {deleted}, 转移 {len(transferred)}, 跳过 {skipped}")
    if transferred:
        with open(os.path.join(args.target_dir, "_transferred.json"), "w", encoding="utf-8") as f:
            json.dump(transferred, f, ensure_ascii=False, indent=2)
        print(f"转移记录已保存到 {args.target_dir}/_transferred.json")


if __name__ == "__main__":
    asyncio.run(main())
