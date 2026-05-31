"""nhentai tag_id → tag_name 映射，数据文件可定期更新。"""
import json
from pathlib import Path

_DB: dict[str, str] = {}
_DATA_PATH = Path(__file__).parent / "data" / "nhentai_tags.json"


def _load():
    global _DB
    if _DATA_PATH.exists():
        _DB = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return _DB


def get_tag_name(tag_id: int | str) -> str | None:
    return (_DB or _load()).get(str(tag_id))


async def update_from_api():
    """从 nhentai API 更新标签映射表（需要 cf_clearance）。"""
    # nhentai 没有公开的标签列表 API，暂不实现自动更新
    # 可手动替换 data/nhentai_tags.json
    pass
