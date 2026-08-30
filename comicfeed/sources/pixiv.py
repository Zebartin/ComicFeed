"""pixiv 源插件：画师/榜单 → Gallery、作品 → 页面。

凭 refresh_token 访问 app-api（OAuth 2.0，X-Client-Time/X-Client-Hash 签名）。
API 与图片请求需 iOS App 身份，图片下载需 Referer。
"""

import asyncio
import hashlib
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


class PixivSource(BaseSource):
    key = "pixiv"
    name = "Pixiv"
    version = "0.1.0"
    domains = ["app-api.pixiv.net"]
    auth_schema = AuthSchema.TOKEN

    _BASE = "https://app-api.pixiv.net"
    _CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
    _CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
    _HASH_SECRET = "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c"
    _UA = "PixivIOSApp/7.19.1 (iOS 16.6; iPhone14,5)"
    _RANK_MODES = {"daily": "day", "weekly": "week", "monthly": "month",
                   "male": "male", "female": "female", "rookie": "rookie"}

    def __init__(self, proxy=None, credentials=None,
                 transport: httpx.AsyncBaseTransport | None = None, time_fn=None):
        super().__init__(proxy=proxy, credentials=credentials)
        self._transport = transport
        self._time = time_fn or time.time
        self._access_token = ""
        self._expires_at = 0.0

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
            return f"pixiv:user:{m.group(1)}"
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
            headers={"User-Agent": self._UA},
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
            f"{self._BASE}/auth/token",
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
    def _match_content(item: dict, content: str) -> bool:
        itype = item.get("type", "")
        if content == "ugoira":
            return itype == "ugoira"
        if content == "manga":
            return itype == "illust" and int(item.get("page_count") or 0) > 1
        return itype == "illust"

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

    def _build_collection_detail(self, gallery_id: str, items: list[dict], content: str,
                                 title: str = "") -> GalleryDetail:
        from comicfeed.infrastructure.log import get
        _log = get(__name__)
        page_ids, page_urls, tags, writers = [], [], set(), set()
        cover_url = ""
        for item in items:
            if item.get("type") == "ugoira":
                _log.info("pixiv 跳过动图作品（暂未支持，04 转换）: %s %s",
                          item.get("id"), item.get("title", ""))
                continue
            if not cover_url:
                cover_url = (item.get("image_urls") or {}).get("medium", "")
            writers.add((item.get("user") or {}).get("name", ""))
            for t in item.get("tags", []):
                tag = t.get("translated_name") or t.get("name")
                if tag:
                    tags.add(tag)
            for pid, purl in self._work_pages(item):
                page_ids.append(pid)
                page_urls.append(purl)
        if not title:
            _, mode, _content = gallery_id.split(":", 2)
            title = f"pixiv {mode} {content}"
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

    async def _fetch_user_items(self, client: httpx.AsyncClient, uid: str, offset: int = 0):
        resp = await client.get(f"{self._BASE}/v1/user/illusts",
                                params={"user_id": uid, "offset": offset},
                                headers={"Authorization": f"Bearer {self._access_token}"})
        if resp.status_code != 200:
            raise PixivAuthError(f"画师作品请求失败: HTTP {resp.status_code}")
        j = resp.json()
        return j.get("illusts") or [], bool(j.get("next_url"))

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
                detail = self._build_collection_detail(gallery_id, items, content)
            elif gallery_id.startswith("user:"):
                uid = gallery_id.split(":", 1)[1]
                items = []
                offset = 0
                while True:
                    page_items, has_next = await self._fetch_user_items(client, uid, offset)
                    items.extend(page_items)
                    if not has_next:
                        break
                    offset += 30
                items = sorted(items, key=lambda it: str(it.get("id", "")).zfill(12))
                detail = self._build_collection_detail(gallery_id, items, "illust",
                                                       title=f"user:{uid}")
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
        async with self._client() as client:
            await self._ensure_token(client)
            if gallery_id.startswith("user:"):
                uid = gallery_id.split(":", 1)[1]
                if old_ids:
                    items, _ = await self._fetch_user_items(client, uid)
                else:
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
                items = sorted(items, key=lambda it: str(it.get("id", "")).zfill(12))
                detail = self._build_collection_detail(gallery_id, items, "illust",
                                                       title=f"user:{uid}")
            elif gallery_id.startswith("ranking:"):
                _, _, content = gallery_id.split(":", 2)
                items = await self._fetch_ranking_items(client, gallery_id, content)
                detail = self._build_collection_detail(gallery_id, items, content)
            else:
                return UpdateResult()
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

    # --- 以下方法由后续工单实现（05/06/07） ---

    async def search(self, query: str, page: int, sort: str = "date") -> SearchResult:
        raise NotImplementedError
