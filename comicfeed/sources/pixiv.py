"""pixiv 源插件：画师/榜单 → Gallery、作品 → 页面。

凭 refresh_token 访问 app-api（OAuth 2.0，X-Client-Time/X-Client-Hash 签名）。
API 与图片请求需 iOS App 身份，图片下载需 Referer。
"""

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

import httpx

from comicfeed.sources.base import (
    AuthSchema,
    BaseSource,
    GalleryDetail,
    GallerySummary,
    SearchResult,
    UpdateResult,
)


class PixivAuthError(Exception):
    """refresh_token 无效、过期或未配置。"""


# 动图转换产物与跳过说明（跨源实例共享：check 时转换、download 时消费）
_webp_cache: dict[str, tuple[float, bytes]] = {}
_webp_ttl = 3000.0
_skip_notes: list[dict] = []


class PixivSource(BaseSource):
    key = "pixiv"
    name = "Pixiv"
    version = "0.1.0"
    domains = ["app-api.pixiv.net"]
    auth_schema = AuthSchema.TOKEN

    _BASE = "https://app-api.pixiv.net"
    _AUTH = "https://oauth.secure.pixiv.net"  # token 端点在 oauth 域名，不在 app-api
    _CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
    _CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
    _HASH_SECRET = "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c"
    _UA = "PixivIOSApp/7.19.1 (iOS 16.6; iPhone14,5)"
    _RANK_MODES = {
        "daily": "day", "weekly": "week", "monthly": "month",
        "male": "day_male", "female": "day_female", "rookie": "week_rookie",
        "daily_r18": "day_r18", "weekly_r18": "week_r18",
        "male_r18": "day_male_r18", "female_r18": "day_female_r18",
        "weekly_r18g": "week_r18g",
        "daily_ai": "day_ai", "weekly_ai": "week_ai", "monthly_ai": "month_ai",
        "daily_r18_ai": "day_r18_ai", "weekly_r18_ai": "week_r18_ai",
        "monthly_r18_ai": "month_r18_ai",
    }
    _RANK_MODE_LABELS = {
        "daily": "日", "weekly": "周", "monthly": "月", "rookie": "新人",
        "male": "男性", "female": "女性",
        "daily_r18": "日R-18", "weekly_r18": "周R-18",
        "male_r18": "男性R-18", "female_r18": "女性R-18",
        "weekly_r18g": "周R-18G",
        "daily_ai": "日AI", "weekly_ai": "周AI", "monthly_ai": "月AI",
        "daily_r18_ai": "日R-18AI", "weekly_r18_ai": "周R-18AI",
        "monthly_r18_ai": "月R-18AI",
    }
    _CONTENT_LABELS = {"illust": "插画", "manga": "漫画", "ugoira": "动图"}

    def __init__(self, proxy=None, credentials=None,
                 transport: httpx.AsyncBaseTransport | None = None, time_fn=None):
        super().__init__(proxy=proxy, credentials=credentials)
        self._transport = transport
        self._time = time_fn or time.time
        self._access_token = ""
        self._expires_at = 0.0
        self._next_url = ""  # 搜索游标翻页（与 exhentai 同机制）

    def get_config_schema(self) -> list[dict]:
        return [
            {"key": "proxy", "label": "代理", "type": "text",
             "placeholder": "空=全局, -=直连", "hint": "留空沿用全局代理"},
            {"key": "refresh_token", "label": "refresh_token", "type": "password",
             "credential": True, "placeholder": "pixiv 的 refresh_token（OAuth）",
             "hint": "长期凭证，加密存储。R-18 内容显示取决于账号设置：pixiv 设置 → 浏览与显示 → 显示敏感内容（未开启时 R-18 作品/榜单会被静默过滤）。"},
        ]

    def parse_url(self, url: str) -> str | None:
        m = re.match(r"https?://(?:www\.)?pixiv\.net/(?:en/)?users/(\d+)", url)
        if m:
            return f"pixiv:user_{m.group(1)}"
        u = urlparse(url)
        if u.hostname not in ("www.pixiv.net", "pixiv.net") or u.path != "/ranking.php":
            return None
        qs = parse_qs(u.query)
        mode = (qs.get("mode") or [""])[0]
        content = (qs.get("content") or [""])[0]
        if not mode or not content:
            return None
        return f"pixiv:ranking:{mode}:{content}"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            proxy=self.proxy,
            timeout=30,
            headers={"User-Agent": self._UA, "Accept-Language": "zh-hans"},
            transport=self._transport,
        )

    def _auth_headers(self) -> dict[str, str]:
        ts = str(int(self._time()))
        return {"X-Client-Time": ts,
                "X-Client-Hash": hashlib.md5((ts + self._HASH_SECRET).encode("utf-8")).hexdigest()}

    async def _refresh_token(self, client: httpx.AsyncClient) -> None:
        rt = self.credentials.get("refresh_token", "")
        if not rt:
            raise PixivAuthError("未配置 refresh_token，请在源配置中填写")
        resp = await client.post(
            f"{self._AUTH}/auth/token",
            data={"client_id": self._CLIENT_ID, "client_secret": self._CLIENT_SECRET,
                  "grant_type": "refresh_token", "refresh_token": rt, "get_secure_url": "1"},
            headers=self._auth_headers(),
        )
        if resp.status_code != 200:
            raise PixivAuthError("refresh_token 无效或已过期，请重新获取")
        data = resp.json()
        token = data.get("access_token", "")
        if not token:
            raise PixivAuthError("token 响应缺少 access_token")
        self._access_token = token
        self._expires_at = self._time() + float(data.get("expires_in", 3600)) - 60

    async def _ensure_token(self, client: httpx.AsyncClient) -> None:
        if not self._access_token or self._time() >= self._expires_at:
            await self._refresh_token(client)

    async def test_connection(self) -> tuple[bool, str]:
        async with self._client() as client:
            try:
                await self._ensure_token(client)
                resp = await client.get(f"{self._BASE}/v1/illust/ranking", params={"mode": "day"},
                                        headers={"Authorization": f"Bearer {self._access_token}"})
                if resp.status_code == 200:
                    return True, "连接成功"
                return False, f"API 返回 HTTP {resp.status_code}"
            except PixivAuthError as e:
                return False, str(e)
            except Exception as e:
                return False, f"连接失败: {e}"

    # --- 作品/集合构建 ---

    @staticmethod
    def _has_cjk(s: str) -> bool:
        return any("\u4e00" <= ch <= "\u9fff" for ch in s)

    @classmethod
    def _pick_tag(cls, t: dict) -> str | None:
        """官方中文优先；官方翻译是罗马音/英文（无汉字）时回退日文原文。"""
        name = t.get("name") or ""
        translated = t.get("translated_name") or ""
        if not name:
            return translated or None
        if not translated:
            return name
        if cls._has_cjk(translated):
            return translated
        if cls._has_cjk(name):
            return name  # 罗马音/英文翻译不如原文可读
        return translated  # 两边都无汉字（如 ASCII 标签），用官方翻译

    @staticmethod
    def _match_content(item: dict, content: str) -> bool:
        itype = item.get("type", "")
        if content == "ugoira":
            return itype == "ugoira"
        if content == "manga":
            return itype == "illust" and int(item.get("page_count") or 0) > 1
        # content=illust：插画（含多页）+ 动图混排（动图转 WebP 进同一卷）
        return itype in ("illust", "ugoira")

    def _work_pages(self, item: dict) -> list[tuple[str, str]]:
        """作品的全部原图页：[(page_native_id, url)]。"""
        wid = str(item.get("id", ""))
        pages = []
        metas = item.get("meta_pages") or []
        if metas:
            for i, meta in enumerate(metas):
                url = (meta.get("image_urls") or {}).get("original", "")
                if url:
                    pages.append((f"{wid}_p{i}", url))
        else:
            single = item.get("meta_single_page") or {}
            url = single.get("original_image_url", "")
            if url:
                pages.append((f"{wid}_p0", url))
        return pages

    async def _convert_ugoira(self, client: httpx.AsyncClient, item: dict, gallery_id: str = "") -> bytes | None:
        """动图 → 动画 WebP。失败时记录跳过说明并返回 None。"""
        import io
        import zipfile
        from PIL import Image
        from comicfeed.infrastructure.log import get
        _log = get(__name__)
        wid = str(item.get("id", ""))
        title = item.get("title", "") or wid
        try:
            resp = await client.get(f"{self._BASE}/v1/ugoira/metadata", params={"illust_id": wid},
                                    headers={"Authorization": f"Bearer {self._access_token}"})
            if resp.status_code != 200:
                raise PixivAuthError(f"元数据 HTTP {resp.status_code}")
            meta = resp.json().get("ugoira_metadata") or {}
            zurls = meta.get("zip_urls") or {}
            zip_url = zurls.get("medium") or zurls.get("large", "")
            if not zip_url:
                raise PixivAuthError("元数据缺少 zip_urls")
            zresp = await client.get(zip_url, headers={"Referer": "https://app-api.pixiv.net"})
            zresp.raise_for_status()
            frames = meta.get("frames") or []
            images, durations = [], []
            with zipfile.ZipFile(io.BytesIO(zresp.content)) as zf:
                for fmeta in frames:
                    fname = fmeta.get("file", "")
                    if not fname:
                        continue
                    im = Image.open(io.BytesIO(zf.read(fname))).convert("RGB")
                    images.append(im)
                    durations.append(int(fmeta.get("delay") or 0))
            if not images:
                raise PixivAuthError("帧列表为空")
            buf = io.BytesIO()
            if len(images) == 1:
                images[0].save(buf, "WEBP")
            else:
                images[0].save(buf, "WEBP", save_all=True, append_images=images[1:],
                               duration=durations, loop=0)
            data = buf.getvalue()
            _webp_cache[wid] = (time.time(), data)
            return data
        except Exception as e:
            _log.warning("pixiv 动图转换失败: %s %s - %r", wid, title, e)
            _skip_notes.append({"gallery_id": gallery_id, "title": title,
                                 "error": f"动图转换失败: {e}"})
            return None

    def pop_download_notes(self) -> list[dict]:
        """下载服务调用：取走并清空本源积累的跳过说明（一次性消费）。"""
        notes, _skip_notes[:] = list(_skip_notes), []
        return notes

    @classmethod
    def _collection_title(cls, gallery_id: str) -> str:
        _, mode, content = gallery_id.split(":", 2)
        c = cls._CONTENT_LABELS.get(content, content)
        m = cls._RANK_MODE_LABELS.get(mode, mode)
        return f"Pixiv {c}{m}榜"

    async def _build_collection_detail(self, client: httpx.AsyncClient, gallery_id: str,
                                       items: list[dict], content: str) -> GalleryDetail:
        from comicfeed.infrastructure.log import get
        _log = get(__name__)
        page_ids, page_urls, tags, writers = [], [], set(), set()
        cover_url = ""
        is_user = gallery_id.startswith("user_")
        for item in items:
            # 诊断：输出原始标签对，供人工核对官方翻译策略（name=translated_name）
            _log.info("pixiv 标签明细 gallery=%s work=%s: %s", gallery_id, item.get("id"),
                      " | ".join(f"{t.get('name')}={t.get('translated_name')}"
                                 for t in (item.get("tags") or [])) or "(无标签)")
            if not cover_url:
                cover_url = (item.get("image_urls") or {}).get("medium", "")
            if is_user:
                writers.add((item.get("user") or {}).get("name", ""))
            for t in item.get("tags", []):
                tag = self._pick_tag(t)
                if tag:
                    tags.add(tag)
            if item.get("type") == "ugoira":
                data = await self._convert_ugoira(client, item, gallery_id)
                if data is None:
                    continue
                wid = str(item.get("id", ""))
                page_ids.append(f"{wid}_webp")
                page_urls.append(f"pixiv-webp:{wid}")
                continue
            for pid, purl in self._work_pages(item):
                page_ids.append(pid)
                page_urls.append(purl)
        if is_user:
            uid = gallery_id.split("_", 1)[1]
            name = next(((it.get("user") or {}).get("name", "") for it in items), "")
            title = f"{name}({uid})" if name else gallery_id
        else:
            title = self._collection_title(gallery_id)
        return GalleryDetail(
            native_id=gallery_id,
            title=title,
            cover_url=cover_url,
            web_url="",
            page_urls=page_urls,
            page_native_ids=page_ids,
            tags=sorted(t for t in tags if t),
            writers=sorted(w for w in writers if w),
            reported_pages=len(page_ids),
        )

    async def _fetch_ranking_items(self, client: httpx.AsyncClient, gallery_id: str, content: str) -> list[dict]:
        _, mode, _content = gallery_id.split(":", 2)
        app_mode = self._RANK_MODES.get(mode)
        if not app_mode:
            raise PixivAuthError(f"不支持的榜单模式: {mode}")
        resp = await client.get(f"{self._BASE}/v1/illust/ranking", params={"mode": app_mode},
                                headers={"Authorization": f"Bearer {self._access_token}"})
        if resp.status_code != 200:
            raise PixivAuthError(f"榜单请求失败: HTTP {resp.status_code}")
        return [it for it in (resp.json().get("illusts") or []) if self._match_content(it, content)]

    async def _fetch_all_user_items(self, client: httpx.AsyncClient, uid: str, max_pages: int) -> list[dict]:
        """翻页收集画师作品。max_pages: 0=只翻第 1 页；1=翻到底；≥2=上限 N 页。"""
        items, fetched = [], 0
        offset = 0
        while True:
            page_items, has_next = await self._fetch_user_items(client, uid, offset)
            items.extend(page_items)
            fetched += 1
            if not has_next:
                break
            if max_pages == 0:
                break
            if max_pages >= 2 and fetched >= max_pages:
                break
            offset += 30
        return items

    async def _fetch_user_items(self, client: httpx.AsyncClient, uid: str, offset: int = 0):
        resp = await client.get(f"{self._BASE}/v1/user/illusts",
                                params={"user_id": uid, "offset": offset},
                                headers={"Authorization": f"Bearer {self._access_token}"})
        if resp.status_code != 200:
            raise PixivAuthError(f"画师作品请求失败: HTTP {resp.status_code}")
        j = resp.json()
        return j.get("illusts") or [], bool(j.get("next_url"))

    def _apply_work_filters(self, items: list[dict], filters_json: str) -> list[dict]:
        """订阅筛选条件按作品逐个应用（收藏数/页数/上传日期），不达标的作品不收录。"""
        if not filters_json:
            return items
        try:
            rules = json.loads(filters_json)
        except (json.JSONDecodeError, TypeError):
            return items
        if not rules:
            return items
        from comicfeed.services.subscription import _matches_filter
        kept = []
        for it in items:
            g = GallerySummary(
                native_id=str(it.get("id", "")),
                title=it.get("title", ""),
                cover_url="",
                page_count=int(it.get("page_count") or 0),
                num_favorites=int(it.get("total_bookmarks") or 0),
                upload_date=(it.get("create_date") or "")[:10],
            )
            if _matches_filter(g, rules):
                kept.append(it)
        return kept

    @staticmethod
    def _ranking_url(gallery_id: str) -> str:
        _, mode, content = gallery_id.split(":", 2)
        return f"https://www.pixiv.net/ranking.php?mode={mode}&content={content}"

    async def get_gallery(self, gallery_id: str, gallery_url: str = "") -> GalleryDetail:
        from comicfeed.infrastructure import gallery_cache as _gc
        upd = _gc.update_cache_get(gallery_id)
        if upd:
            return upd
        key = gallery_url or gallery_id
        cached = _gc.cache_get(key)
        if cached:
            return cached
        async with self._client() as client:
            await self._ensure_token(client)
            if gallery_id.startswith("ranking:"):
                _, _, content = gallery_id.split(":", 2)
                items = await self._fetch_ranking_items(client, gallery_id, content)
                detail = await self._build_collection_detail(client, gallery_id, items, content)
            elif gallery_id.startswith("user_"):
                uid = gallery_id.split("_", 1)[1]
                items = await self._fetch_all_user_items(client, uid, 1)
                items = sorted(items, key=lambda it: str(it.get("id", "")).zfill(12))
                detail = await self._build_collection_detail(client, gallery_id, items, "illust")
            else:
                raise NotImplementedError("pixiv 作品详情由后续工单实现")
        detail.web_url = gallery_url or (self._ranking_url(gallery_id)
                                         if gallery_id.startswith("ranking:") else "")
        _gc.cache_set(key, detail)
        return detail

    def _updates_from(self, detail: GalleryDetail, old_ids, gallery_url: str = "") -> UpdateResult:
        from comicfeed.infrastructure import gallery_cache as _gc
        old = set(old_ids or [])
        keep_idx = [i for i, pid in enumerate(detail.page_native_ids) if pid not in old]
        if not keep_idx:
            return UpdateResult()
        filtered = GalleryDetail(
            native_id=detail.native_id, title=detail.title, cover_url=detail.cover_url,
            web_url=gallery_url or detail.web_url,
            page_urls=[detail.page_urls[i] for i in keep_idx],
            page_native_ids=[detail.page_native_ids[i] for i in keep_idx],
            tags=list(detail.tags), writers=list(detail.writers),
            upload_date=detail.upload_date, reported_pages=len(keep_idx),
            num_favorites=detail.num_favorites,
        )
        _gc.update_cache_set(detail.native_id, filtered)
        return UpdateResult(has_updates=True, gallery=GallerySummary(
            native_id=detail.native_id, title=detail.title, cover_url=detail.cover_url,
            web_url=filtered.web_url, page_count=len(keep_idx), tags=list(detail.tags),
            new_page_ids=[detail.page_native_ids[i] for i in keep_idx],
            detail=filtered,
        ))

    async def check_updates(self, gallery_id: str, last_known: dict, gallery_url: str = "") -> UpdateResult:
        old_ids = last_known.get("page_ids") or []
        max_pages = int(last_known.get("max_pages") or 0)
        filters = last_known.get("filters") or ""
        async with self._client() as client:
            await self._ensure_token(client)
            if gallery_id.startswith("user_"):
                uid = gallery_id.split("_", 1)[1]
                if old_ids:
                    items, _ = await self._fetch_user_items(client, uid)
                else:
                    items = await self._fetch_all_user_items(client, uid, max_pages)
                items = self._apply_work_filters(items, filters)
                items = sorted(items, key=lambda it: str(it.get("id", "")).zfill(12))
                detail = await self._build_collection_detail(client, gallery_id, items, "illust")
            elif gallery_id.startswith("ranking:"):
                _, _, content = gallery_id.split(":", 2)
                items = await self._fetch_ranking_items(client, gallery_id, content)
                items = self._apply_work_filters(items, filters)
                detail = await self._build_collection_detail(client, gallery_id, items, content)
            else:
                raise NotImplementedError(f"不支持的 pixiv 画廊 ID: {gallery_id}")
        return self._updates_from(detail, old_ids, gallery_url)

    async def download_pages(self, gallery_id: str, page_range: slice, gallery_url: str = "",
                             detail: GalleryDetail | None = None,
                             on_page: Callable[[], None] | None = None) -> list[bytes]:
        from comicfeed.infrastructure.config import get_setting
        from comicfeed.infrastructure.log import get
        _log = get(__name__)
        _retry = int(await get_setting("download_retry") or 3)
        if detail is None:
            detail = await self.get_gallery(gallery_id, gallery_url=gallery_url)
        urls = detail.page_urls[page_range]
        headers = {"Referer": "https://app-api.pixiv.net", "User-Agent": self._UA}
        async with httpx.AsyncClient(proxy=self.proxy, timeout=30, follow_redirects=True,
                                     headers=headers, transport=self._transport) as client:
            results = []
            for i, url in enumerate(urls):
                if url.startswith("pixiv-webp:"):
                    wid = url.split(":", 1)[1]
                    entry = _webp_cache.get(wid)
                    if not entry or time.time() - entry[0] >= _webp_ttl:
                        raise RuntimeError(f"动图转换数据已过期，请重新检查订阅: {wid}")
                    results.append(entry[1])
                    if on_page:
                        on_page()
                    continue
                last_err = None
                for attempt in range(_retry):
                    try:
                        resp = await client.get(url)
                        resp.raise_for_status()
                        results.append(resp.content)
                        if on_page:
                            on_page()
                        break
                    except Exception as e:
                        last_err = e
                        if attempt < _retry - 1:
                            await asyncio.sleep(1)
                else:
                    _log.error("下载图片失败(重试%d次): gallery=%s page=%d - %r",
                               _retry, gallery_id, page_range.start + i + 1, last_err)
                    raise last_err
        return results

    # --- 搜索页透传（07） ---

    _SORTS = {"date": "date_desc", "date_desc": "date_desc", "date_asc": "date_asc"}

    def get_sort_options(self) -> list[dict]:
        return [
            {"value": "date_desc", "label": "最新"},
            {"value": "date_asc", "label": "最旧"},
        ]

    async def search(self, query: str, page: int, sort: str = "date") -> SearchResult:
        async with self._client() as client:
            await self._ensure_token(client)
            if page > 1 and self._next_url:
                url, params = self._next_url, None
            else:
                url = f"{self._BASE}/v1/search/illust"
                params = {"word": query, "sort": self._SORTS.get(sort, "date_desc")}
                if page > 1:
                    params["offset"] = (page - 1) * 30
            resp = await client.get(url, params=params,
                                    headers={"Authorization": f"Bearer {self._access_token}"})
            if resp.status_code != 200:
                raise PixivAuthError(f"搜索失败: HTTP {resp.status_code}")
            data = resp.json()
            self._next_url = data.get("next_url") or ""
            return self._parse_search(data, page)

    def _parse_search(self, data: dict, page: int) -> SearchResult:
        from comicfeed.io.cbz import normalize_title
        items = []
        for it in data.get("illusts") or []:
            tags = [self._pick_tag(t) for t in (it.get("tags") or [])]
            items.append(GallerySummary(
                native_id=str(it.get("id", "")),
                title=normalize_title(it.get("title", "")),
                cover_url=(it.get("image_urls") or {}).get("medium", ""),
                web_url=f"https://www.pixiv.net/artworks/{it.get('id', '')}",
                page_count=int(it.get("page_count") or 0),
                num_favorites=int(it.get("total_bookmarks") or 0),
                tags=[t for t in tags if t],
            ))
        return SearchResult(items=items, total_pages=0, current_page=page, next_url=self._next_url)
