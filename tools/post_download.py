"""下载后归类脚本：根据画廊 tags 将 CBZ 移动到对应目录。

用法：由 ComicFeed 在下载批次完成后自动调用，stdin 接收 JSON。

配置 (post_download.toml)，放在脚本同目录:
  [dirs]
  magazine = "./_magazine"
  artist = "./_artist"
  hot = "./_hot"

  [rules]
  magazine_tags = ["杂志", "magazine", "anthology", "合集"]

归类优先级：杂志 > 画师 > 热门（兜底，无需移动）。
"""
import json
import os
import shutil
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib

CONFIG_PATH = Path(__file__).with_name("post_download.toml")

DEFAULT_DIRS = {
    "magazine": "./_magazine",
    "artist": "./_artist",
    "hot": "./_hot",
}

DEFAULT_MAGAZINE_TAGS = ["杂志", "magazine", "anthology", "合集"]


def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            cfg = tomllib.load(f)
    else:
        cfg = {}
    dirs = {**DEFAULT_DIRS, **cfg.get("dirs", {})}
    rules = cfg.get("rules", {})
    magazine_tags = rules.get("magazine_tags", DEFAULT_MAGAZINE_TAGS)
    return dirs, magazine_tags


def classify(tags: list[str], magazine_tags: list[str]) -> str:
    """根据 tags 归类：magazine | artist | hot。"""
    for t in tags:
        tl = t.lower()
        for mt in magazine_tags:
            if mt.lower() in tl:
                return "magazine"
    for t in tags:
        if t.startswith("画师：") or t.startswith("artist:"):
            return "artist"
    return "hot"


def main():
    dirs, magazine_tags = load_config()

    raw = sys.stdin.read()
    if not raw.strip():
        return
    data = json.loads(raw)
    galleries = data.get("galleries", [])

    moved = 0
    for g in galleries:
        files = g.get("files", [])
        tags = g.get("tags", [])
        title = g.get("title", "?")

        category = classify(tags, magazine_tags)

        target_dir = dirs.get(category)
        if not target_dir:
            continue
        target_dir = os.path.abspath(target_dir)
        os.makedirs(target_dir, exist_ok=True)

        for f in files:
            src = os.path.abspath(f)
            if not os.path.isfile(src):
                continue
            dest_dir = target_dir
            # 如果已在目标目录则跳过
            if os.path.dirname(src) == dest_dir:
                continue

            dest = os.path.join(dest_dir, os.path.basename(f))

            if category == "hot":
                # 热门是兜底目录，不需要移动（其他订阅下载的画廊不应归入热门）
                # 但如果当前不在热门目录且类别为hot，跳过不移动
                continue

            try:
                shutil.move(src, dest)
                print(f"[{category}] {os.path.basename(f)}")
                moved += 1
            except OSError as e:
                print(f"移动失败: {os.path.basename(f)}: {e}", file=sys.stderr)

    if moved:
        print(f"归类完成: 移动 {moved} 个文件")


if __name__ == "__main__":
    main()
