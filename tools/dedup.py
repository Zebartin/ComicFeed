"""ComicFeed 存量去重工具：通过页面 dHash 比对检测同一作者内重复/子集漫画。

用法:
  uv run python tools/dedup.py -c dedup.toml

配置文件 (dedup.toml):
  [komga]
  url = "http://localhost:25600"
  user = ""
  pass = ""
  series_ids = ["abc123"]

  [dedup]
  jaccard_threshold = 0.7
  subset_threshold = 0.8
  hamming_distance = 5

依赖: httpx, tkinter, Pillow, imagehash, tomli (Python<3.11 需安装)
"""
import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import tkinter as tk
from io import BytesIO
from itertools import combinations
from pathlib import Path
from zipfile import ZipFile

try:
    import tomllib
except ImportError:
    import tomli as tomllib

import httpx
import imagehash
from PIL import Image


# ── 路径 / 文件 ──────────────────────────────────────────────

def komga_path_to_real(komga_path: str) -> str | None:
    """将 Komga 返回的 url 转换为操作系统实际路径。"""
    return komga_path.replace("/komga", "//fnos/komga")


def open_file(path: str):
    if os.name == "nt":
        os.startfile(Path(path))
    elif os.name == "posix":
        subprocess.run(["xdg-open", path])


# ── Komga API ────────────────────────────────────────────────

async def get_all_books(base_url: str, library_ids: list[str], auth: str) -> list[dict]:
    """获取指定系列中所有未删除的 book。"""
    books = []
    page = 0
    payload = {
        "condition": {
            "allOf": [{
                "deleted": {"operator": "isFalse"}
            }, {
                "oneShot": {"operator": "isTrue"}
            }, {
                "anyOf": [{"libraryId": {"operator": "is", "value": lid}} for lid in library_ids]
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
            content = data.get("content", [])
            if not content:
                break
            books.extend(content)
            if data.get("last"):
                break
            page += 1
    return books


# ── 作者分组 ─────────────────────────────────────────────────

def _get_group_writer(authors: list[dict]) -> str | None:
    """从 Komga metadata.authors 中提取用于分组的 writer。
    优先"画师"前缀，其次"团队"前缀，最后取第一个 writer。"""
    names = [a["name"] for a in authors if a.get("role") == "writer"]
    if not names:
        return None
    for n in names:
        if n.startswith("画师"):
            return n
    for n in names:
        if n.startswith("团队"):
            return n
    return names[0]


def group_by_writer(books: list[dict]) -> dict[str, list[dict]]:
    """按 writer 分组 book。没有 writer 的归入 None。"""
    groups: dict[str | None, list[dict]] = {}
    for b in books:
        authors = b.get("metadata", {}).get("authors", [])
        key = _get_group_writer(authors)
        groups.setdefault(key, []).append(b)
    return groups


# ── dHash 计算 & 缓存 ────────────────────────────────────────

def _compute_cbz_hashes(real_path: str) -> list[str]:
    """逐页计算 CBZ 内图片的 dHash，返回 hex 字符串列表。"""
    hashes = []
    with ZipFile(real_path, "r") as z:
        for name in sorted(z.namelist()):
            if name.endswith("/") or name.lower().endswith(".xml"):
                continue
            try:
                data = z.read(name)
                img = Image.open(BytesIO(data)).convert("L")
                h = str(imagehash.dhash(img))
                hashes.append(h)
            except Exception:
                hashes.append("")
    return hashes


def _load_cache(cache_path: str) -> dict:
    """加载缓存，兼容旧格式并清理已删除文件。"""
    if not os.path.exists(cache_path):
        return {"hashes": {}, "compared": [], "results": {}}
    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 旧格式迁移：旧版根级存 {path: {mtime, hashes}}，改为 {"hashes": {path: ...}}
    if "hashes" not in data:
        hashes = {}
        for k, v in data.items():
            if isinstance(v, dict) and "mtime" in v and "hashes" in v:
                hashes[k] = v
        data = {"hashes": hashes, "compared": [], "results": {}}
    # 清理已删除文件
    existing = set()
    for path in list(data["hashes"]):
        if os.path.exists(path):
            existing.add(path)
        else:
            del data["hashes"][path]
    data["compared"] = [p for p in data.get("compared", []) if os.path.exists(p)]
    for key in list(data.get("results", {})):
        a, b = key.split("|", 1)
        if not os.path.exists(a) or not os.path.exists(b):
            del data["results"][key]
    return data


def _save_cache(cache_path: str, cache: dict):
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def get_hashes(real_path: str, cache: dict) -> list[str]:
    """获取 CBZ 的页面哈希，优先读缓存（比较 mtime）。"""
    try:
        mtime = os.path.getmtime(real_path)
    except OSError:
        return []
    key = str(Path(real_path))
    hashes_cache = cache.setdefault("hashes", {})
    entry = hashes_cache.get(key)
    if entry and entry.get("mtime") == mtime:
        return entry["hashes"]
    hashes = _compute_cbz_hashes(real_path)
    hashes_cache[key] = {"mtime": mtime, "hashes": hashes}
    return hashes


# ── 重复检测 ─────────────────────────────────────────────────

def _hamming_match(h1: str, h2: str, max_dist: int) -> bool:
    if not h1 or not h2:
        return False
    return imagehash.hex_to_hash(h1) - imagehash.hex_to_hash(h2) <= max_dist


def _find_matches(pages_a: list[str], pages_b: list[str], max_dist: int):
    """返回 (匹配数, A中匹配页索引集合, B中匹配页索引集合)。"""
    matched_a: set[int] = set()
    matched_b: set[int] = set()
    for i, ha in enumerate(pages_a):
        if not ha:
            continue
        for j, hb in enumerate(pages_b):
            if not hb or j in matched_b:
                continue
            if _hamming_match(ha, hb, max_dist):
                matched_a.add(i)
                matched_b.add(j)
                break  # 每页只匹配一次
    return len(matched_a), matched_a, matched_b


def _pair_key(a: str, b: str) -> str:
    return f"{a}|{b}" if a < b else f"{b}|{a}"


def detect_duplicates(books: list[dict], cache: dict,
                       jaccard_threshold: float, subset_threshold: float,
                       hamming_distance: int) -> list[dict]:
    """检测组内重复/子集。结果缓存于 cache["compared"] 和 cache["results"]。"""
    book_entries = []
    for b in books:
        real_path = komga_path_to_real(b.get("url", ""))
        if not real_path or not os.path.exists(real_path):
            continue
        hashes = get_hashes(real_path, cache)
        if not hashes:
            continue
        book_entries.append({
            "book": b,
            "real_path": real_path,
            "hashes": hashes,
            "page_count": len(hashes),
        })

    # 比对缓存
    compared_set = set(cache.setdefault("compared", []))
    results_cache = cache.setdefault("results", {})

    edges: list[tuple[int, int, float, str]] = []
    total_pairs = len(book_entries) * (len(book_entries) - 1) // 2
    checked = 0
    skipped = 0

    for (i, a), (j, b) in combinations(enumerate(book_entries), 2):
        pa, pb = a["real_path"], b["real_path"]
        pk = _pair_key(pa, pb)

        if pa in compared_set and pb in compared_set:
            cached = results_cache.get(pk)
            if cached:
                edges.append((i, j, cached.get("jaccard", 0), cached["subtype"]))
                skipped += 1
            continue

        match_count, matched_a, matched_b = _find_matches(
            a["hashes"], b["hashes"], hamming_distance,
        )
        checked += 1
        if total_pairs > 20 and checked % 20 == 0:
            print(f"    增量比对: {checked}")

        if match_count == 0:
            continue
        union = a["page_count"] + b["page_count"] - match_count
        jaccard = match_count / union if union > 0 else 0
        a_in_b = match_count / a["page_count"] if a["page_count"] > 0 else 0
        b_in_a = match_count / b["page_count"] if b["page_count"] > 0 else 0

        # print(jaccard, a_in_b, b_in_a)
        subtype = None
        if jaccard >= jaccard_threshold:
            subtype = "duplicate"
        elif a_in_b >= subset_threshold and a["page_count"] < b["page_count"]:
            subtype = "subset"
        elif b_in_a >= subset_threshold and b["page_count"] < a["page_count"]:
            subtype = "superset"
        if subtype:
            results_cache[pk] = {"match_count": match_count, "jaccard": jaccard, "subtype": subtype}
            edges.append((i, j, jaccard if subtype == "duplicate" else (a_in_b if subtype == "subset" else b_in_a), subtype))

    # 本轮所有文件均已处理完毕，标记为已比对
    for entry in book_entries:
        compared_set.add(entry["real_path"])
    cache["compared"] = list(compared_set)

    if skipped > 0:
        print(f"    缓存命中: {skipped} 对")
    if not edges:
        return []

    # Union-Find 聚类
    n = len(book_entries)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i, j, _, _ in edges:
        union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    results = []
    for indices in clusters.values():
        if len(indices) < 2:
            continue
        idx_map = {orig: local for local, orig in enumerate(indices)}
        group_books = [book_entries[i] for i in indices]
        group_edges = [
            {"i": idx_map[i], "j": idx_map[j], "score": score, "subtype": subtype}
            for (i, j, score, subtype) in edges
            if i in indices and j in indices
        ]
        results.append({
            "books": group_books,
            "pairs": group_edges,
        })
    return results


# ── UI ────────────────────────────────────────────────────────

class DedupDialog:
    def __init__(self, root: tk.Tk, group_name: str, dup_groups: list[dict],
                 group_index: int, total_groups: int):
        self.root = root
        self.group_name = group_name
        self.dup_groups = dup_groups
        self.result = None  # "delete" or "skip"
        self._vars: list[tk.BooleanVar] = []

        root.title("ComicFeed 去重")
        root.geometry("900x650")
        root.minsize(600, 400)
        root.protocol("WM_DELETE_WINDOW", lambda: self._skip())

        # 标题
        tk.Label(root, text=f"作者: {group_name or '(未分组)'}",
                 font=("", 14, "bold")).pack(pady=10)

        # 重复组
        canvas = tk.Canvas(root)
        scrollbar = tk.Scrollbar(root, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        def _on_canvas_resize(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", _on_canvas_resize)

        canvas.pack(side="left", fill="both", expand=True, padx=10)
        scrollbar.pack(side="right", fill="y")

        for di, dg in enumerate(dup_groups):
            # 重复组标签
            pair_texts = []
            for p in dg["pairs"]:
                if p["subtype"] == "duplicate":
                    pair_texts.append(f"重复 (Jaccard {p['score']:.0%})")
                elif p["subtype"] == "subset":
                    pair_texts.append(f"子集 (覆盖率 {p['score']:.0%})")
                else:
                    pair_texts.append(f"超集 (覆盖率 {p['score']:.0%})")
            frame = tk.LabelFrame(scroll_frame,
                                  text=f"重复组 {di + 1}: {', '.join(pair_texts)}",
                                  font=("", 10, "bold"), padx=10, pady=5)
            frame.pack(fill="x", pady=5)

            # 默认选中页数最多的
            max_pages = max(e["page_count"] for e in dg["books"])
            for entry in dg["books"]:
                b = entry["book"]
                path = entry["real_path"]
                pages = entry["page_count"]
                name = b.get("name", b.get("metadata", {}).get("title", "?"))

                row = tk.Frame(frame)
                row.pack(fill="x", pady=2)

                var = tk.BooleanVar(value=(pages == max_pages))
                self._vars.append(var)
                tk.Checkbutton(row, variable=var).pack(side="left")
                tk.Label(row, text=f"[{b.get('metadata', {}).get('number', '?')}] {name}",
                         font=("", 10), anchor="w").pack(side="left", fill="x", expand=True)
                tk.Label(row, text=f"{pages}页", fg="gray", font=("", 9)).pack(side="left", padx=5)
                tk.Button(row, text="打开", command=lambda p=path: open_file(p),
                          font=("", 8), padx=6).pack(side="left", padx=5)

        # 底部按钮
        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=15)
        tk.Button(btn_frame, text="保留选中并删除其余", command=self._delete,
                  bg="#e74c3c", fg="white", width=20, height=2).pack(side="left", padx=10)
        tk.Button(btn_frame, text=f"跳过 ({group_index + 1}/{total_groups})",
                  command=self._skip, width=15, height=2).pack(side="left", padx=10)

    def _get_files_to_delete(self) -> list[str]:
        """返回要删除的文件路径列表（未勾选的 book）。"""
        to_delete = []
        var_idx = 0
        for dg in self.dup_groups:
            for entry in dg["books"]:
                if not self._vars[var_idx].get():
                    to_delete.append(entry["real_path"])
                var_idx += 1
        return to_delete

    def _delete(self):
        files = self._get_files_to_delete()
        if files:
            for f in files:
                try:
                    os.remove(f)
                    print(f"  已删除: {os.path.basename(f)}")
                except OSError as e:
                    print(f"  删除失败: {os.path.basename(f)}: {e}")
        self.result = "delete"

    def _skip(self):
        self.result = "skip"


# ── 主流程 ───────────────────────────────────────────────────

def _load_config(path: str) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _make_auth(user: str, passwd: str) -> str:
    if not user:
        return ""
    return "Basic " + base64.b64encode(f"{user}:{passwd}".encode()).decode()


async def _precompute_hashes(all_books: list[dict], cache: dict) -> int:
    """并行预计算所有未缓存 CBZ 的页面哈希。返回新计算的数量。"""
    hashes_cache = cache.setdefault("hashes", {})
    to_compute = []
    for b in all_books:
        path = komga_path_to_real(b.get("url", ""))
        if not path or not os.path.exists(path):
            continue
        key = str(Path(path))
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if hashes_cache.get(key, {}).get("mtime") == mtime:
            continue
        to_compute.append(path)

    if not to_compute:
        return 0

    print(f"计算 {len(to_compute)} 个 CBZ 的页面哈希...")
    loop = asyncio.get_event_loop()
    tasks = [loop.run_in_executor(None, _compute_cbz_hashes, p) for p in to_compute]

    completed = 0
    batch_size = max(1, os.cpu_count() or 4)
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i + batch_size]
        results = await asyncio.gather(*batch)
        for path, hashes in zip(to_compute[i:i + batch_size], results):
            key = str(Path(path))
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                mtime = 0
            hashes_cache[key] = {"mtime": mtime, "hashes": hashes}
            completed += 1
        print(f"  进度: {completed}/{len(to_compute)}")

    return completed


async def _process_group(writer: str, group_books: list[dict], cache: dict,
                        cache_path: str,
                        jaccard_threshold: float, subset_threshold: float,
                        hamming_distance: int) -> dict | None:
    """处理一组：计算未缓存 CBZ 的哈希 + 检测重复。"""
    n = await _precompute_hashes(group_books, cache)
    if n > 0:
        _save_cache(cache_path, cache)
    total_pairs = len(group_books) * (len(group_books) - 1) // 2
    print(f"  检测重复 ({len(group_books)} 本, {total_pairs} 对)...")
    prev_compared = len(cache.get("compared", []))
    dup_groups = await asyncio.to_thread(
        detect_duplicates, group_books, cache,
        jaccard_threshold, subset_threshold, hamming_distance,
    )
    if len(cache.get("compared", [])) > prev_compared:
        _save_cache(cache_path, cache)
    if dup_groups:
        return {"writer": writer, "dup_groups": dup_groups}
    return None


async def _show_dialog(group: dict, gi: int, total: int):
    """展示 tkinter 对话框，期间释放控制权给 asyncio。"""
    root = tk.Tk()
    dialog = DedupDialog(root, group["writer"], group["dup_groups"], gi, total)

    while dialog.result is None:
        root.update()
        await asyncio.sleep(0.05)

    try:
        root.destroy()
    except Exception:
        pass
    return dialog.result


async def main():
    parser = argparse.ArgumentParser(description="ComicFeed 去重工具")
    parser.add_argument("-c", "--config", required=True, help="TOML 配置文件路径")
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"配置文件不存在: {args.config}")
        sys.exit(1)

    cfg = _load_config(args.config)

    komga_cfg = cfg.get("komga", {})
    dedup_cfg = cfg.get("dedup", {})

    base = komga_cfg.get("url", "http://localhost:25600").rstrip("/")
    library_ids = komga_cfg.get("library_ids", [])
    if not library_ids:
        print("错误: 必须在配置文件中设置 komga.library_ids")
        sys.exit(1)

    komga_auth = _make_auth(komga_cfg.get("user", ""), komga_cfg.get("pass", ""))

    jaccard_threshold = dedup_cfg.get("jaccard_threshold", 0.7)
    subset_threshold = dedup_cfg.get("subset_threshold", 0.8)
    hamming_distance = dedup_cfg.get("hamming_distance", 5)
    cache_path = dedup_cfg.get("cache_path", "page_hashes.json")

    print("获取 Komga 书籍列表...")
    books = await get_all_books(base, library_ids, komga_auth)
    print(f"共 {len(books)} 本书")

    if not books:
        print("没有找到任何书籍")
        return

    # 按 writer 分组，过滤单本组
    groups = group_by_writer(books)
    groups = {k: v for k, v in groups.items() if k is not None and len(v) >= 2}
    if not groups:
        print("没有需要处理的分组（每组至少 2 本）")
        return

    print(f"共 {len(groups)} 个作者分组")

    # 加载缓存，后续每组处理完都会保存
    cache = _load_cache(cache_path)

    groups_items = list(groups.items())
    total_groups = len(groups_items)

    # 后台持续处理所有组，结果放入队列
    results_queue: asyncio.Queue = asyncio.Queue()

    async def process_all():
        for writer, group_books in groups_items:
            result = await _process_group(
                writer, group_books, cache, cache_path,
                jaccard_threshold, subset_threshold, hamming_distance,
            )
            await results_queue.put((writer, result))
        await results_queue.put(None)  # 哨兵，表示处理完毕

    bg_task = asyncio.create_task(process_all())

    dup_count = 0
    deleted_total = 0
    processed = 0

    while True:
        item = await results_queue.get()
        if item is None:
            break
        writer, result = item
        processed += 1

        if not result:
            print(f"处理: {writer} — 无重复")
            continue

        dup_count += 1
        g = result
        print(f"[{dup_count}] {g['writer']}")
        for di, dg in enumerate(g["dup_groups"]):
            for p in dg["pairs"]:
                b_i = dg["books"][p["i"]]["book"]
                b_j = dg["books"][p["j"]]["book"]
                print(f"  {b_i.get('name', '?')} ↔ {b_j.get('name', '?')} "
                      f"({p['subtype']}, {p['score']:.0%})")

        print(f"\n{'='*60}")
        print(f"已发现 {dup_count} 个作者有重复漫画（已处理 {processed}/{total_groups} 个分组）\n")

        r = await _show_dialog(g, dup_count - 1, total_groups)
        if r == "delete":
            deleted_total += 1

    if dup_count == 0:
        print("\n未发现重复漫画")
        return

    print(f"\n全部完成: 处理了 {deleted_total}/{dup_count} 个有重复的分组")


if __name__ == "__main__":
    asyncio.run(main())
