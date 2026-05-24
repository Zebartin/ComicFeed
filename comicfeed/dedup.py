from difflib import SequenceMatcher
from itertools import combinations

from comicfeed.cbz import normalize_title

_DEDUP_THRESHOLD = 0.8


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def find_similar_groups(items: list) -> list[list]:
    """阶段 1：按归一化标题相似度分组。

    返回候选组列表（相似度 > 0.8 的项目归为一组）。
    没有相似项的返回空列表。
    """
    # 归一化标题
    normalized = {item.native_id: normalize_title(item.title) for item in items}
    # 并查集分组
    parent = {item.native_id: item.native_id for item in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for a, b in combinations(items, 2):
        na = normalized[a.native_id]
        nb = normalized[b.native_id]
        if _similarity(na, nb) > _DEDUP_THRESHOLD:
            union(a.native_id, b.native_id)

    # 按根收集分组
    groups: dict[str, list] = {}
    for item in items:
        root = find(item.native_id)
        groups.setdefault(root, []).append(item)

    # 只返回有重复的组（size > 1）
    return [g for g in groups.values() if len(g) > 1]
