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
            resp = await client.get(
                f"{self._BASE}/api/v2/search",
                params={"query": query, "page": page, "sort": sort},
            )
            resp.raise_for_status()
            return self._parse_search_response(resp.json(), page)

    @staticmethod
    def _make_image_url(base: str, path: str) -> str:
        """拼接图片 URL，兼容 path 有无前导 /。"""
        return f"{base}{path}" if path.startswith("/") else f"{base}/{path}"

    def _parse_search_response(self, data: dict, page: int) -> SearchResult:
        items = []
        for item in data.get("result", []):
            thumbnail = item.get("thumbnail", "")
            cover_url = self._make_image_url("https://t.nhentai.net", thumbnail) if thumbnail else ""
            items.append(GallerySummary(
                native_id=str(item.get("id", "")),
                title=item.get("japanese_title") or item.get("english_title", ""),
                cover_url=cover_url,
                page_count=item.get("num_pages", 0),
            ))
        return SearchResult(
            items=items,
            total_pages=data.get("num_pages", 0),
            current_page=page,
        )

    async def get_gallery(self, gallery_id: str) -> GalleryDetail:
        async with self._client() as client:
            resp = await client.get(f"{self._BASE}/api/v2/galleries/{gallery_id}")
            resp.raise_for_status()
            return self._parse_gallery_response(resp.json())

    def _parse_gallery_response(self, data: dict) -> GalleryDetail:
        title_data = data.get("title", {})
        title = title_data.get("japanese") or title_data.get("pretty", "")
        cover = data.get("cover", {})
        cover_path = cover.get("path", "")
        cover_url = self._make_image_url("https://t.nhentai.net", cover_path) if cover_path else ""

        tags = [t.get("name", "") for t in data.get("tags", [])]

        page_urls = []
        for p in data.get("pages", []):
            path = p.get("path", "")
            if path:
                page_urls.append(self._make_image_url("https://i.nhentai.net", path))

        native_id = str(data.get("id", ""))
        return GalleryDetail(
            native_id=native_id,
            title=title,
            cover_url=cover_url,
            web_url=f"https://nhentai.net/g/{native_id}/",
            page_urls=page_urls,
            tags=tags,
            reported_pages=len(page_urls),
        )

    async def download_pages(self, gallery_id: str, page_range: slice) -> list[bytes]:
        detail = await self.get_gallery(gallery_id)
        urls = detail.page_urls[page_range]
        async with self._client() as client:
            results = []
            for url in urls:
                resp = await client.get(url)
                resp.raise_for_status()
                results.append(resp.content)
        return results

    async def check_updates(self, gallery_id: str, last_known: dict) -> UpdateResult:
        return UpdateResult()
