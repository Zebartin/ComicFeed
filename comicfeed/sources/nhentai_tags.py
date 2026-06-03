"""nhentai tag_id → tag_name 映射。本地缓存 + API 自动补全。"""
import asyncio
import json
from pathlib import Path

_DB: dict[str, str] = {}
_DATA_PATH = Path(__file__).parent.parent / "data" / "nhentai_tags.json"


def _load():
    global _DB
    if _DATA_PATH.exists():
        _DB = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return _DB


def _save():
    _DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    _DATA_PATH.write_text(json.dumps(_DB, ensure_ascii=False, indent=2), encoding="utf-8")


def get_tag_name(tag_id: int | str) -> str | None:
    return (_DB or _load()).get(str(tag_id))


async def resolve_tags(tag_ids: list[int], client) -> dict[str, str]:
    """批量获取标签名。先查本地，未知的从 API 补全。返回 {id: name}。"""
    _DB or _load()
    result = {}
    unknown = []
    for tid in tag_ids:
        name = _DB.get(str(tid))
        if name:
            result[str(tid)] = name
        else:
            unknown.append(str(tid))

    if unknown:
        try:
            from comicfeed.infrastructure.http_retry import retry_get
            resp = await retry_get(client, "https://nhentai.net/api/v2/tags/ids",
                                   params={"ids": ",".join(unknown)})
            for tag in resp.json():
                tid = str(tag["id"])
                name = tag.get("name", "")
                if name:
                    _DB[tid] = name
                    result[tid] = name
            asyncio.create_task(_async_save())
        except Exception:
            pass  # 标签补全失败不阻塞搜索

    return result


async def _async_save():
    try:
        _save()
    except Exception:
        pass
