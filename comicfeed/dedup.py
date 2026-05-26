from difflib import SequenceMatcher
from itertools import combinations

from comicfeed.cbz import normalize_title

_DEDUP_THRESHOLD = 0.999


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def find_similar_groups(items: list) -> list[list]:
    """阶段 1：按归一化标题相似度分组。

    返回候选组列表（相似度 > _DEDUP_THRESHOLD 的项目归为一组）。
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


_PAGE_DIFF_THRESHOLD = 0.15


def resolve_duplicates(candidates: list[tuple[str, int]]) -> set[str]:
    """阶段 2：根据实际页数比较，返回应保留的 ID 集合。

    候选列表中的每一项为 (gallery_id, actual_page_count)。
    页数差异 ≤15% 视为重复，保留页数多者；页数相同保留 ID 较大者。
    页数差异 >15% 则都保留。
    """
    # 按页数降序排列，页数相同时按 ID 数值降序
    def _sort_key(x):
        nid, pages = x
        try:
            return (pages, int(nid))
        except ValueError:
            return (pages, 0)

    sorted_candidates = sorted(candidates, key=_sort_key, reverse=True)
    keep: set[str] = set()
    rejected: set[str] = set()

    for i, (id_a, pages_a) in enumerate(sorted_candidates):
        if id_a in rejected:
            continue
        keep.add(id_a)
        for j, (id_b, pages_b) in enumerate(sorted_candidates):
            if i == j or id_b in rejected or id_b in keep:
                continue
            if pages_a == 0:
                continue
            diff = abs(pages_a - pages_b) / pages_a
            if diff <= _PAGE_DIFF_THRESHOLD:
                rejected.add(id_b)

    return keep
