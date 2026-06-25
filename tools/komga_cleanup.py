"""Komga 书架清理工具：遍历已读书籍，逐个决定删除或转移。

用法:
  uv run python tools/komga_cleanup.py -c cleanup.toml

配置文件 (cleanup.toml):
  [komga]
  url = "http://localhost:25600"
  user = ""
  pass = ""
  library_id = ""
  target_dir = "./_transferred"
  series_ids = ["abc123", "def456"]

  [comicfeed]
  url = "http://localhost:8000"
  user = ""
  pass = ""

依赖: httpx, tkinter (Python 自带), tomli (Python<3.11 需安装)
"""
import argparse
import asyncio
import base64
import os
import re
import subprocess
import sys
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from urllib.parse import urlencode

try:
    import tomllib
except ImportError:
    import tomli as tomllib

import httpx

# ── 预留接口：Komga 路径 → 实际文件路径 ──────────────────────────

def komga_path_to_real(komga_path: str) -> str | None:
    """将 Komga 返回的 url 转换为操作系统实际路径。"""
    return komga_path.replace("/komga", "//fnos/komga")


# ── 预留接口：打开文件 ──────────────────────────────────────────

def open_file(path: str):
    """用系统默认程序打开文件。"""
    if os.name == "nt":
        os.startfile(Path(path))
    elif os.name == "posix":
        subprocess.run(["xdg-open", path])


# ── Komga API ────────────────────────────────────────────────────

async def get_series_books(base_url: str, series_ids: list[str], auth: str) -> list[dict]:
    """获取所有已读且可用的 book。"""
    books = []
    page = 0
    payload = {
        "condition": {
            "allOf": [{
                "deleted": {
                    "operator": "isFalse",
                }
            }, {
                "readStatus": {
                    "operator": "is",
                    "value": "READ"
                }
            }, {
                "anyOf": [{
                    "seriesId": {
                        "operator": "is",
                        "value": sid
                    }
                } for sid in series_ids]
            }]
        },
    }
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            r = await client.post(
                f"{base_url}/api/v1/books/list",
                params={"page": page, "size": 100, "unpaged": "true"},
                json=payload,
                headers={
                    "Authorization": auth,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
            )
            r.raise_for_status()
            data = r.json()
            # with open('./t.json', 'w', encoding='utf-8') as f:
            #     import json
            #     json.dump(data, f, ensure_ascii=False, indent=2)
            # exit()
            content = data.get("content", [])
            if not content:
                break
            books.extend(
                b for b in content
                if b.get("number", 1) != 1
            )
            if data.get("last"):
                break
            page += 1
    return books


async def trigger_komga_scan(base_url: str, auth: str, library_id: str):
    """触发 Komga 库扫描。"""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{base_url}/api/v1/libraries/{library_id}/scan",
            headers={"Authorization": auth},
        )
        r.raise_for_status()


async def poll_and_mark_read(base_url: str, auth: str, library_id: str,
                              pending_books: list[dict]):
    """轮询 Komga 直到转移的书籍出现并标记已读。"""
    if not pending_books:
        return

    timeout = 30 * 60  # 30 分钟
    interval = 10      # 30 秒
    start = time.time()

    async with httpx.AsyncClient(timeout=30) as client:
        while pending_books:
            elapsed = time.time() - start
            if elapsed > timeout:
                print(f"\n超时 ({timeout // 60} 分钟): {len(pending_books)} 本书籍未找到")
                for b in pending_books:
                    print(f"  - {b['title']}")
                sys.exit(1)

            await asyncio.sleep(interval)

            title_conditions = [
                {"title": {"operator": "contains", "value": b["title"]}}
                for b in pending_books
            ]
            payload = {
                "condition": {
                    "allOf": [
                        {"libraryId": {"operator": "is", "value": library_id}},
                        {"mediaStatus": {"operator": "is", "value": "READY"}},
                        {"anyOf": title_conditions}
                    ]
                }
            }
            r = await client.post(
                f"{base_url}/api/v1/books/list",
                params={"unpaged": "true"},
                json=payload,
                headers={
                    "Authorization": auth,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
            )
            r.raise_for_status()
            found_books = r.json().get("content", [])
            found_titles = {b["metadata"]["title"] for b in found_books}

            to_mark = [b for b in pending_books if b["title"] in found_titles]
            for b in to_mark:
                matched = next(c for c in found_books if c["metadata"]["title"] == b["title"])
                book_id = matched["id"]
                try:
                    await client.patch(
                        f"{base_url}/api/v1/books/{book_id}/read-progress",
                        json={"completed": True},
                        headers={"Authorization": auth},
                    )
                    print(f"  已标记已读: {b['title']}")
                except Exception as e:
                    print(f"  标记已读失败 ({b['title']}): {e}")

            pending_books = [b for b in pending_books if b["title"] not in found_titles]

            if pending_books:
                print(f"  等待中... 剩余 {len(pending_books)} 本")


async def get_nhentai_gallery(native_id: str) -> dict:
    """获取 nhentai 画廊详情，返回 API 响应 dict。"""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"https://nhentai.net/api/v2/galleries/{native_id}")
        r.raise_for_status()
        return r.json()


# ── ComicFeed API ────────────────────────────────────────────────

async def create_comicfeed_subscription(cf_url: str, cf_auth: str,
                                         name: str, query: str):
    """调用 ComicFeed API 创建订阅。"""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{cf_url}/api/subscriptions",
            json={
                "name": name,
                "source_key": "nhentai",
                "query": query,
                "cbz_max_pages": 0,
                "use_global_search": True,
            },
            headers={
                "Authorization": cf_auth,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        r.raise_for_status()
        return r.json()


# ── 解析 ─────────────────────────────────────────────────────────

_BRACKET = re.compile(r"\[([^\]]+)\]")


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

    def __init__(self, root: tk.Tk, book: dict, real_path: str, target_dir: str,
                 artists: list[str] | None = None, groups: list[str] | None = None,
                 extract_info: str = "", nhentai_error: str = ""):
        self.root = root
        self.book = book
        self.real_path = real_path
        self.target_dir = target_dir
        self.result: str | None = None  # "delete", "transfer", "skip"
        self._extract_info = extract_info
        self._selected_query: str | None = None
        self._waiting_for_url = False

        root.title("Komga 书架清理")
        root.geometry("500x550")
        root.protocol("WM_DELETE_WINDOW", lambda: root.quit())

        name = book.get("name", book.get("metadata", {}).get("title", "?"))
        tk.Label(root, text=f"标题: {name}", wraplength=460,
                 font=("", 12, "bold")).pack(pady=10, padx=20, anchor="w")
        tk.Label(root, text=f"路径: {real_path}", wraplength=460,
                 fg="gray").pack(padx=20, anchor="w")

        self.btn_frame = tk.Frame(root)
        self.btn_frame.pack(pady=15)
        tk.Button(self.btn_frame, text="删除", command=self._delete,
                  bg="#e74c3c", fg="white", width=12, height=2).pack(side="left", padx=10)
        tk.Button(self.btn_frame, text="转移", command=self._transfer,
                  bg="#3498db", fg="white", width=12, height=2).pack(side="left", padx=10)
        tk.Button(self.btn_frame, text="跳过", command=self._skip,
                  width=12, height=2).pack(side="left", padx=10)

        self.info_label = tk.Label(root, text="", wraplength=460)
        self.info_label.pack(pady=10, padx=20)

        self.url_frame: tk.Frame | None = None

        if nhentai_error:
            self.info_label.config(text=nhentai_error)
        if artists is not None and groups is not None:
            self.show_nhentai_urls(artists, groups)

    def show_nhentai_urls(self, artists: list[str], groups: list[str]):
        """展示 nhentai 搜索 URL 选项（可点击超链接）。"""
        base = "https://nhentai.net/search/?"
        if self.url_frame:
            self.url_frame.destroy()
        self.url_frame = tk.Frame(self.root)
        self.url_frame.pack(pady=5)

        options: list[tuple[str, str]] = []
        lang = "language:chinese"
        if artists and groups:
            a = " ".join(f'artist:"{x}"' for x in artists)
            g = " ".join(f'group:"{x}"' for x in groups)
            options.append((f"{a} {g} {lang}", f"artist+group: {', '.join(artists + groups)}"))
        if artists:
            a = " ".join(f'artist:"{x}"' for x in artists)
            options.append((f"{a} {lang}", f"artist: {', '.join(artists)}"))
        if groups:
            g = " ".join(f'group:"{x}"' for x in groups)
            options.append((f"{g} {lang}", f"group: {', '.join(groups)}"))

        if not options:
            tk.Label(self.url_frame, text="无 artist/group 标签", fg="gray").pack()
            return

        tk.Label(self.url_frame, text="点击按钮创建订阅，点击链接在浏览器打开:",
                 font=("", 10, "bold")).pack(anchor="w")

        for query, label in options:
            full_url = f"{base}{urlencode({'q': query})}"
            frame = tk.Frame(self.url_frame)
            frame.pack(anchor="w", pady=2)
            tk.Button(frame, text=label,
                      command=lambda q=query: self._pick_url(q),
                      bg="#e8f4fd", relief="flat").pack(side="left")
            url_label = tk.Label(frame, text=full_url, fg="blue",
                                 font=("", 8, "underline"), cursor="hand2",
                                 wraplength=400)
            url_label.pack(side="left", padx=8)
            url_label.bind("<Button-1>", lambda e, u=full_url: webbrowser.open(u))

    def _pick_url(self, query: str):
        q = query.split(' ')
        q = [part for part in q if not part.startswith("language")]
        self._selected_query = ' '.join(q)
        self.root.quit()

    def _delete(self):
        self.result = "delete"
        self.root.quit()

    def _transfer(self):
        self.result = "transfer"
        self._waiting_for_url = True
        self.btn_frame.destroy()
        self.info_label.config(text="请选择搜索链接以创建订阅，或直接关闭窗口仅转移")

    def _skip(self):
        self.result = "skip"
        self.root.quit()


# ── 主流程 ───────────────────────────────────────────────────────

def _load_config(path: str) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _make_auth(user: str, passwd: str) -> str:
    if not user:
        return ""
    return "Basic " + base64.b64encode(f"{user}:{passwd}".encode()).decode()


async def main():
    parser = argparse.ArgumentParser(description="Komga 书架清理工具")
    parser.add_argument("-c", "--config", required=True, help="TOML 配置文件路径")
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"配置文件不存在: {args.config}")
        sys.exit(1)

    cfg = _load_config(args.config)

    komga_cfg = cfg.get("komga", {})
    cf_cfg = cfg.get("comicfeed", {})

    base = komga_cfg.get("url", "http://localhost:25600").rstrip("/")
    target_dir = komga_cfg.get("target_dir", "./_transferred")
    series_ids = komga_cfg.get("series_ids", [])
    library_id = komga_cfg.get("library_id", "")

    if not series_ids:
        print("错误: 必须在配置文件中设置 komga.series_ids")
        sys.exit(1)

    komga_auth = _make_auth(komga_cfg.get("user", ""), komga_cfg.get("pass", ""))

    cf_url = cf_cfg.get("url", "").rstrip("/")
    cf_auth = _make_auth(cf_cfg.get("user", ""), cf_cfg.get("pass", ""))

    os.makedirs(target_dir, exist_ok=True)
    books = await get_series_books(base, series_ids, komga_auth)

    print(f"\n{'='*60}")
    print(f"找到 {len(books)} 本已读书籍")

    transferred = []
    deleted = 0
    skipped = 0

    for i, book in enumerate(books):
        name = book.get("name", book.get("metadata", {}).get("title", "?"))
        komga_path = book.get("url", "")
        if not komga_path:
            print(f"\n[{i+1}/{len(books)}] {name} — 无文件路径，跳过")
            skipped += 1
            continue

        real_path = komga_path_to_real(komga_path)
        if not real_path:
            print(f"\n[{i+1}/{len(books)}] {name} — 路径转换失败，跳过")
            skipped += 1
            continue

        if not os.path.exists(real_path):
            print(f"\n[{i+1}/{len(books)}] {name} — 文件不存在，跳过")
            skipped += 1
            continue

        print(f"\n[{i+1}/{len(books)}] {name}")
        open_file(real_path)

        # 提前查询 nhentai 信息
        nhentai_id = book.get("metadata", {}).get("number", "")
        title = book.get("metadata", {}).get("title", "")
        extract_info = extract_bracket_title(title)

        artists = None
        groups = None
        nhentai_error = ""
        if nhentai_id:
            try:
                gallery = await get_nhentai_gallery(nhentai_id)
                artists, groups = extract_artist_group(gallery)
            except Exception as e:
                nhentai_error = f"获取画廊信息失败: {e}"
        else:
            nhentai_error = "无 nhentai 画廊 ID"

        root = tk.Tk()
        dialog = BookDialog(root, book, real_path, target_dir,
                            artists=artists, groups=groups,
                            extract_info=extract_info,
                            nhentai_error=nhentai_error)
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
            # 创建 ComicFeed 订阅
            if dialog._selected_query and cf_url:
                sub_name = f"作者 - {dialog._extract_info}"
                try:
                    await create_comicfeed_subscription(cf_url, cf_auth, sub_name, dialog._selected_query)
                    print(f"  订阅已创建: {sub_name}")
                except Exception as e:
                    print(f"  创建订阅失败: {e}")

            dest = os.path.join(target_dir, os.path.basename(real_path))
            os.rename(real_path, dest)
            transferred.append({
                "name": name,
                "title": book.get("metadata", {}).get("title", ""),
                "from": real_path,
                "to": dest,
            })
            print(f"  已转移到 {dest}")
        else:
            skipped += 1
            print(f"  已跳过")

    print(f"\n{'='*60}")
    print(f"全部完成: 删除 {deleted}, 转移 {len(transferred)}, 跳过 {skipped}")
    if transferred:
        print("\n转移详情:")
        for item in transferred:
            print(f"  {item['name']}: {item['from']} → {item['to']}")

    # 转移后：触发 Komga 扫描 + 轮询标记已读
    if transferred and library_id:
        print(f"\n{'='*60}")
        print("触发 Komga 库扫描...")
        try:
            await trigger_komga_scan(base, komga_auth, library_id)
            print("扫描已触发，等待书籍就绪...")
        except Exception as e:
            print(f"触发扫描失败: {e}")
            return

        pending = [{"title": b["title"]} for b in transferred if b["title"]]
        await poll_and_mark_read(base, komga_auth, library_id, pending)


if __name__ == "__main__":
    asyncio.run(main())
