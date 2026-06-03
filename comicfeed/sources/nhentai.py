import asyncio
import os
import re

from curl_cffi.requests import AsyncSession

from comicfeed.sources.base import (
    AuthSchema,
    BaseSource,
    GalleryDetail,
    GallerySummary,
    SearchResult,
    UpdateResult,
)


class NhentaiSource(BaseSource):
    key = "nhentai"
    name = "nHentai"
    version = "0.1.0"
    domains = ["nhentai.net"]
    auth_schema = AuthSchema.COOKIE  # cf_clearance

    _URL_PATTERN = re.compile(r"https?://(?:www\.)?nhentai\.net/g/(\d+)")
    _BASE = "https://nhentai.net"

    def get_sort_options(self) -> list[dict]:
        return [
            {"value": "date", "label": "最新"},
            {"value": "popular-today", "label": "今日热门"},
            {"value": "popular-week", "label": "本周热门"},
            {"value": "popular", "label": "全部热门"},
        ]

    def get_config_schema(self) -> list[dict]:
        return [
            {"key": "proxy", "label": "代理", "type": "text", "placeholder": "空=全局, -=直连", "hint": "留空沿用全局代理"},
            {"key": "csrftoken", "label": "csrftoken", "type": "text", "credential": True, "placeholder": "从浏览器 Cookie 中获取"},
            {"key": "cf_clearance", "label": "cf_clearance", "type": "text", "credential": True, "placeholder": "从浏览器 Cookie 中获取"},
        ]

    def parse_url(self, url: str) -> str | None:
        m = self._URL_PATTERN.match(url)
        if m:
            return f"nhentai:{m.group(1)}"
        return None

    def _cookies(self) -> dict[str, str]:
        return dict(self.credentials)

    def _client(self) -> AsyncSession:
        return AsyncSession(
            proxy=self.proxy,
            impersonate="chrome131",
            timeout=30,
            cookies=self._cookies(),
        )

    async def search(self, query: str, page: int, sort: str = "date") -> SearchResult:
        async with self._client() as client:
            from comicfeed.infrastructure.http_retry import retry_get
            resp = await retry_get(client, f"{self._BASE}/api/v2/search",
                                   params={"query": query, "page": page, "sort": sort})
            return await self._parse_search_response(resp.json(), page, client)

    @staticmethod
    def _make_image_url(base: str, path: str) -> str:
        """拼接图片 URL，兼容 path 有无前导 /。"""
        return f"{base}{path}" if path.startswith("/") else f"{base}/{path}"

    async def _parse_search_response(self, data: dict, page: int, client) -> SearchResult:
        # 收集全部 tag_id，批量查询
        from comicfeed.sources.nhentai_tags import resolve_tags
        from comicfeed.infrastructure.tag_translator import get_translator as _gt
        all_ids = set()
        for item in data.get("result", []):
            all_ids.update(item.get("tag_ids", []))
        tag_map = await resolve_tags(list(all_ids), client) if all_ids else {}
        _tt = _gt()

        items = []
        for item in data.get("result", []):
            thumbnail = item.get("thumbnail", "")
            cover_url = self._make_image_url("https://t.nhentai.net", thumbnail) if thumbnail else ""
            tids = item.get("tag_ids", [])
            english = [tag_map.get(str(t)) for t in tids]
            tags = [_tt.translate("", t) for t in english if t]
            tags = [t for t in tags if t]
            nid = str(item.get("id", ""))
            from comicfeed.io.cbz import normalize_title
            raw_title = item.get("japanese_title") or item.get("english_title", "")
            items.append(GallerySummary(
                native_id=nid,
                title=normalize_title(raw_title),
                cover_url=cover_url,
                web_url=f"https://nhentai.net/g/{nid}/",
                page_count=item.get("num_pages", 0),
                num_favorites=item.get("num_favorites", 0),
                tag_ids=tids,
                tags=[t for t in tags if t],
            ))
        return SearchResult(
            items=items,
            total_pages=data.get("num_pages", 0),
            current_page=page,
        )

    async def get_gallery(self, gallery_id: str, gallery_url: str = "") -> GalleryDetail:
        async with self._client() as client:
            from comicfeed.infrastructure.http_retry import retry_get
            resp = await retry_get(client, f"{self._BASE}/api/v2/galleries/{gallery_id}")
            return self._parse_gallery_response(resp.json())

    def _parse_gallery_response(self, data: dict) -> GalleryDetail:
        from comicfeed.io.cbz import normalize_title
        title_data = data.get("title", {})
        title = normalize_title(title_data.get("japanese") or title_data.get("pretty", ""))
        cover = data.get("cover", {})
        cover_path = cover.get("path", "")
        cover_url = self._make_image_url("https://t.nhentai.net", cover_path) if cover_path else ""

        from comicfeed.infrastructure.tag_translator import get_translator
        _tt = get_translator()
        tags = []
        writers = []
        _WRITER_TYPES = {"artist", "group", "画师", "团队"}
        for t in data.get("tags", []):
            ns = t.get("type", "")
            name = t.get("name", "")
            if not name:
                continue
            translated = _tt.translate(ns, name)
            if ns in _WRITER_TYPES:
                writers.append(translated)
            else:
                tags.append(translated)

        page_urls = []
        page_native_ids = []
        for p in data.get("pages", []):
            path = p.get("path", "")
            if path:
                page_urls.append(self._make_image_url("https://i.nhentai.net", path))
                page_native_ids.append(os.path.basename(path))

        native_id = str(data.get("id", ""))
        upload_ts = data.get("upload_date", 0)
        upload_date = ""
        if upload_ts:
            from datetime import datetime
            upload_date = datetime.fromtimestamp(upload_ts).strftime("%Y-%m-%d")
        return GalleryDetail(
            native_id=native_id,
            title=title,
            cover_url=cover_url,
            web_url=f"https://nhentai.net/g/{native_id}/",
            page_urls=page_urls,
            page_native_ids=page_native_ids,
            tags=tags,
            writers=writers,
            upload_date=upload_date,
            reported_pages=len(page_urls),
            num_favorites=data.get("num_favorites", 0),
        )

    async def download_pages(self, gallery_id: str, page_range: slice, gallery_url: str = "", detail: GalleryDetail | None = None) -> list[bytes]:
        from comicfeed.infrastructure.config import get_setting
        _retry = int(await get_setting("download_retry"))
        if detail is None:
            detail = await self.get_gallery(gallery_id, gallery_url=gallery_url)
        urls = detail.page_urls[page_range]
        import httpx
        from comicfeed.infrastructure.log import get
        _log = get(__name__)
        async with httpx.AsyncClient(proxy=self.proxy, timeout=30, follow_redirects=True) as client:
            results = []
            for i, url in enumerate(urls):
                last_err = None
                for attempt in range(_retry):
                    try:
                        resp = await client.get(url)
                        resp.raise_for_status()
                        results.append(resp.content)
                        break
                    except Exception as e:
                        last_err = e
                        if attempt < _retry - 1:
                            await asyncio.sleep(1)
                else:
                    _log.error("下载图片失败(重试%d次): gallery=%s page=%d - %r", _retry,
                               gallery_id, page_range.start + i + 1, last_err)
                    raise last_err
        return results

    async def check_updates(self, gallery_id: str, last_known: dict, gallery_url: str = "") -> UpdateResult:
        return UpdateResult()
