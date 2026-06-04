"""订阅检查服务：SEARCH 搜索去重 + SPECIFIC_GALLERY 更新检测。"""
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from comicfeed.services.dedup import _similarity, find_similar_groups, resolve_duplicates
from comicfeed.io.cbz import normalize_title
from comicfeed.infrastructure.log import get
from comicfeed.models import Subscription
from comicfeed.repositories.gallery import existing_ids, existing_titles as _load_titles
from comicfeed.repositories.page import ids_for_gallery
from comicfeed.sources.base import BaseSource, GallerySummary

_log = get(__name__)


def _matches_filter(g: GallerySummary, rules: list[dict]) -> bool:
    import json
    from datetime import datetime, timedelta, timezone
    for r in rules:
        field = r.get("field", "")
        op = r.get("op", "")
        val = r.get("value")
        if field == "upload_date" and op == "since_days":
            if not g.upload_date:
                continue  # 未知，跳过此条件
            try:
                dt = datetime.fromisoformat(g.upload_date)
            except ValueError:
                continue
            cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=int(val))
            if not (dt >= cutoff):
                return False
            continue
        actual = getattr(g, field, None)
        if actual is None:
            continue  # 未知，跳过此条件
        if op == "gte":
            if not (actual >= val):
                return False
        elif op == "lte":
            if not (actual <= val):
                return False
    return True


def _apply_filters(items: list[GallerySummary], rules_json: str) -> list[GallerySummary]:
    if not rules_json:
        return items
    import json
    try:
        rules = json.loads(rules_json)
    except (json.JSONDecodeError, TypeError):
        return items
    if not rules:
        return items
    return [g for g in items if _matches_filter(g, rules)]


async def _build_query(sub, source) -> str:
    """拼接全局搜索条件。exhentai 源会将 tag:xxx 转换为真实 namespace。"""
    if not getattr(sub, 'use_global_search', False):
        return sub.query
    from comicfeed.infrastructure.config import get_setting
    from comicfeed.infrastructure.tag_translator import get_translator
    import json
    _tt = get_translator()
    parts = [sub.query]

    def _expand(item: str) -> list[str]:
        if not item.startswith("tag:") or source.key != "exhentai":
            return [item]
        name = item[4:]
        namespaces = _tt.find_namespaces(name)
        if not namespaces:
            return [f"other:{name}"]
        return [f"{ns}:{name}" for ns in namespaces]

    try:
        defaults = json.loads(await get_setting("search_defaults"))
        for item in defaults:
            parts.extend(_expand(str(item)))
    except Exception:
        pass
    try:
        blocklist = json.loads(await get_setting("search_blocklist"))
        for item in blocklist:
            for e in _expand(str(item)):
                parts.append(f"-{e}")
    except Exception:
        pass
    return " ".join(parts)


async def search_and_dedup(
    session: AsyncSession,
    sub: Subscription,
    source: BaseSource,
    max_search_pages: int = 1,
    exclude_ids: set[str] | None = None,
    existing_titles: list[str] | None = None,
    start_page: int = 1,
) -> tuple[list[GallerySummary], bool]:
    """SEARCH 模式：搜索源并去重，返回新画廊列表。"""
    exclude_ids = exclude_ids or set()
    existing_titles = existing_titles or []

    if not existing_titles:
        db_titles = await _load_titles(session, source.key)
        existing_titles.extend(db_titles)

    all_new: list[GallerySummary] = []
    has_more = False

    for page_offset in range(max_search_pages):
        page = start_page + page_offset
        query = await _build_query(sub, source)
        result = await source.search(query, page=page, sort=sub.sort)
        if not result.items:
            break
        has_more = result.next_url or (result.total_pages > page)

        raw_items = [g for g in result.items if g.native_id not in exclude_ids]
        raw_items = _apply_filters(raw_items, sub.filter_rules)
        if not raw_items:
            if has_more:
                continue
            else:
                break

        ids = [f"{source.key}:{item.native_id}" for item in raw_items]
        db_existing = await existing_ids(session, ids)
        new = [g for g in raw_items if f"{source.key}:{g.native_id}" not in db_existing]

        filtered = []
        for g in new:
            nt = normalize_title(g.title)
            if any(_similarity(nt, et) > 0.999 for et in existing_titles):
                continue
            filtered.append(g)
            existing_titles.append(nt)
        new = filtered

        if len(new) > 1:
            groups = find_similar_groups(new)
            if groups:
                keep: set[str] = {g.native_id for g in new}
                for group in groups:
                    candidates = [(g.native_id, g.page_count) for g in group]
                    resolved = resolve_duplicates(candidates)
                    keep -= {g.native_id for g in group}
                    keep |= resolved
                new = [g for g in new if g.native_id in keep]
                _log.info("去重: %d 组候选 → 保留 %d 个", len(groups), len(new))

        all_new.extend(new)
        for g in new:
            exclude_ids.add(g.native_id)

        if not has_more:
            break

    return all_new, has_more


async def track_gallery(
    session: AsyncSession,
    sub: Subscription,
    source: BaseSource,
) -> tuple[list[GallerySummary], bool]:
    """SPECIFIC_GALLERY 模式：检测 newer version + 页面 ID 比对。"""
    gid = sub.query.strip()
    gurl = ""
    parsed = source.parse_url(gid)
    if parsed:
        gurl = gid
        gid = parsed.split(":", 1)[-1]

    full_gid = f"{source.key}:{gid}"
    old_ids = await ids_for_gallery(session, full_gid)

    result = await source.check_updates(gid, {"page_ids": old_ids}, gallery_url=gurl)

    sub.last_checked_at = datetime.now()
    await session.commit()

    if result.has_updates and result.gallery:
        return [result.gallery], False
    return [], False


async def check_subscription(
    session: AsyncSession,
    subscription_id: int,
    source: BaseSource,
    max_search_pages: int = 1,
    exclude_ids: set[str] | None = None,
    existing_titles: list[str] | None = None,
    start_page: int = 1,
) -> tuple[list[GallerySummary], bool]:
    """兼容旧接口：按 sub.mode 分发到 SearchService 或 GalleryTracker。"""
    sub = await session.get(Subscription, subscription_id)
    if sub is None:
        return [], False

    if sub.mode == "SPECIFIC_GALLERY":
        return await track_gallery(session, sub, source)

    new_items, has_more = await search_and_dedup(
        session, sub, source, max_search_pages, exclude_ids, existing_titles, start_page
    )

    if start_page <= 1:
        sub.last_checked_at = datetime.now()
        await session.commit()

    _log.info("订阅 [%s] 检查完成: %d 个新画廊 (翻 %d 页, has_more=%s)",
              sub.name, len(new_items), max_search_pages, has_more)
    return new_items, has_more
