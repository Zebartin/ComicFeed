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
        """从凭证中获取 cookies（cf_clearance 等）。"""
        cookies = {}
        if self.credentials:
            for cred in self.credentials:
                if cred.credential_type == "cookie":
                    cookies[cred.key] = cred.value
        return cookies

    def _client(self) -> AsyncSession:
        return AsyncSession(
            proxy=self.proxy,
            impersonate="chrome131",
            timeout=30,
            cookies=self._cookies(),
        )

    async def search(self, query: str, page: int) -> SearchResult:
        async with self._client() as client:
            resp = await client.get(
                f"{self._BASE}/api/v2/search",
                params={"query": query, "page": page, "sort": "date"},
            )
            resp.raise_for_status()
            return self._parse_search_response(resp.json(), page)

    def _parse_search_response(self, data: dict, page: int) -> SearchResult:
        items = []
        for item in data.get("result", []):
            thumbnail = item.get("thumbnail", "")
            cover_url = f"https://t.nhentai.net{thumbnail}" if thumbnail else ""
            items.append(GallerySummary(
                native_id=str(item.get("id", "")),
                title=item.get("english_title") or item.get("japanese_title", ""),
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
        title = title_data.get("english") or title_data.get("pretty", "")
        cover = data.get("cover", {})
        cover_path = cover.get("path", "")
        cover_url = f"https://t.nhentai.net{cover_path}" if cover_path else ""

        tags = [t.get("name", "") for t in data.get("tags", [])]

        page_urls = []
        for p in data.get("pages", []):
            path = p.get("path", "")
            if path:
                page_urls.append(f"https://i.nhentai.net{path}")

        return GalleryDetail(
            native_id=str(data.get("id", "")),
            title=title,
            cover_url=cover_url,
            page_urls=page_urls,
            tags=tags,
            reported_pages=len(page_urls),
        )

    async def download_pages(self, gallery_id: str, page_range: slice):
        raise NotImplementedError

    async def check_updates(self, gallery_id: str, last_known: dict) -> UpdateResult:
        return UpdateResult()
