"""EhTagTranslation 标签翻译器。

从 GitHub Releases 下载 gzip 压缩的翻译数据库，
缓存到本地，过期后自动更新。
"""
import gzip
import json
from datetime import datetime
from functools import cache
from logging import getLogger

from curl_cffi.requests import AsyncSession

from comicfeed.sources.base import AuthSchema

logger = getLogger(__name__)

REMOTE_URL = "https://raw.githubusercontent.com/EhTagTranslation/DatabaseReleases/refs/heads/master/db.text.json.gz"
UPDATE_DAYS = 15


class TagTranslator:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._namespaces: dict[str, str] = {}
        self._tags: dict[str, dict[str, str]] = {}  # namespace → {en: zh}

    async def load(self):
        """加载本地缓存或从远程下载。"""
        import os
        try:
            mtime = os.path.getmtime(self._db_path)
            age_days = (datetime.now().timestamp() - mtime) / 86400
            if age_days < UPDATE_DAYS:
                with open(self._db_path, encoding="utf-8") as f:
                    db = json.load(f)
                self._namespaces = db.get("namespaces", {})
                self._tags = db.get("tags", {})
                self.find_namespaces.cache_clear()
                logger.info("标签翻译数据库已加载 (%d 个命名空间)", len(self._namespaces))
                return
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        await self._download()

    async def _download(self):
        """从 GitHub 下载并解析翻译数据库。"""
        logger.info("正在下载标签翻译数据库...")
        async with AsyncSession(timeout=30) as s:
            r = await s.get(REMOTE_URL)
            r.raise_for_status()
            raw = gzip.decompress(r.content)
            db_data = json.loads(raw)

        self._namespaces = {}
        self._tags = {}
        for item in db_data.get("data", []):
            ns = item["namespace"]
            if ns == "rows":
                self._namespaces = {k: v["name"] for k, v in item["data"].items()}
                self._namespaces["artist"] = "画师"
            else:
                self._tags[ns] = {k: v["name"] for k, v in item["data"].items()}

        self.find_namespaces.cache_clear()
        with open(self._db_path, "w", encoding="utf-8") as f:
            json.dump({"namespaces": self._namespaces, "tags": self._tags}, f, ensure_ascii=False)
        logger.info("标签翻译数据库已更新 (%d 命名空间, %d 标签)", len(self._namespaces),
                     sum(len(v) for v in self._tags.values()))

    # 需要在标签文本中保留 namespace 前缀的类型
    _SHOW_NS = {"artist", "group", "character", "parody"}

    def _format(self, ns: str, name: str) -> str:
        """格式化标签：关键 namespace 保留前缀，其余省略。"""
        if ns in self._SHOW_NS:
            cn_ns = self._namespaces.get(ns, ns)
            return f"{cn_ns}：{name}"
        return name

    @cache
    def find_namespaces(self, name: str) -> tuple[str, ...]:
        """反查标签名所属的 namespace（仅搜索非 _SHOW_NS）。
        复合标签以 | 分隔时，依次尝试整体和拆分后的各部分。"""
        candidates = [name]
        if "|" in name:
            candidates.extend(p.strip() for p in name.split("|"))
        for cand in candidates:
            result = []
            for ns, tmap in self._tags.items():
                if ns not in self._SHOW_NS and cand in tmap:
                    result.append(ns)
            if result:
                return tuple(result)
        return tuple()

    def translate(self, ns: str, name: str, avoid_ns: set[str] | None = _SHOW_NS) -> str:
        """翻译单个标签。标签以 | 分隔时依次尝试整体和拆分后的各部分。"""
        candidates = [name]
        if "|" in name:
            candidates.extend(p.strip() for p in name.split("|"))
        for cand in candidates:
            result = self._try_translate_one(ns, cand, avoid_ns)
            if result is not None:
                return result
        if ns:
            return self._format(ns, name)
        return name

    def _try_translate_one(self, ns: str, name: str, avoid_ns: set[str] | None) -> str | None:
        """翻译单个标签名，找不到时返回 None。"""
        if ns and ns in self._tags and name in self._tags[ns]:
            return self._format(ns, self._tags[ns][name])
        found = None
        for tns, tmap in self._tags.items():
            if name in tmap:
                if avoid_ns and tns in avoid_ns:
                    found = found or (tns, tmap[name])
                else:
                    return self._format(tns, tmap[name])
        if found:
            return self._format(found[0], found[1])
        return None


# 全局实例
_instance: TagTranslator | None = None


def get_translator(db_path: str = "comicfeed/data/eh_tags.db.json") -> TagTranslator:
    global _instance
    if _instance is None:
        _instance = TagTranslator(db_path)
    return _instance
