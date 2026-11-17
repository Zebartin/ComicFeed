import hashlib
import re
from collections.abc import Callable
from io import BytesIO
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

from comicfeed.infrastructure.http_retry import retry_get
from comicfeed.io.cbz import normalize_title
from comicfeed.sources.base import (
    BaseSource,
    GalleryDetail,
    GallerySummary,
    SearchResult,
    UpdateResult,
)


class FourKHDSource(BaseSource):
    key = "4khd"
    name = "4KHD"
    version = "0.1.0"
    domains = ["www.4khd.com"]
    remove_ads = False
    supports_global_search = False

    _BASE = "https://www.4khd.com"
    _API = f"{_BASE}/wp-json/wp/v2/posts"
    _COUNT = re.compile(r"(\d+)\s*photos\b", re.IGNORECASE)
    _HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": f"{_BASE}/"}

    def __init__(self, *, transport=None, **kwargs):
        super().__init__(**kwargs)
        self._transport = transport

    def get_config_schema(self) -> list[dict]:
        return [{"key": "proxy", "label": "代理", "type": "text",
                 "placeholder": "空=全局, -=直连", "hint": "留空沿用全局代理"}]

    def get_sort_options(self) -> list[dict]:
        return [{"value": "date", "label": "最新"}]

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(proxy=self.proxy, timeout=30, follow_redirects=True,
                                 headers=self._HEADERS, transport=self._transport)

    def parse_url(self, url: str) -> str | None:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in (
            "4khd.com", "www.4khd.com"
        ):
            return None
        match = re.fullmatch(r"/wp-json/wp/v2/posts/(\d+)/?", parsed.path)
        pid = match.group(1) if match else parse_qs(parsed.query).get("p", [""])[0]
        if pid.isdecimal():
            return f"{self.key}:{int(pid)}"
        return None

    async def resolve_url(self, url: str) -> str | None:
        parsed_id = self.parse_url(url)
        if parsed_id:
            return parsed_id
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in (
            "4khd.com", "www.4khd.com"
        ) or not re.fullmatch(r"/content/\d+/[^/]+\.html(?:/\d+)?/?", parsed.path):
            return None
        async with self._client() as client:
            response = await retry_get(client, url)
        soup = BeautifulSoup(response.text, "html.parser")
        for link in soup.find_all("link", attrs={"type": "application/json"}):
            resolved = self.parse_url(urljoin(str(response.url), link.get("href", "")))
            if resolved:
                return resolved
        return None

    @staticmethod
    def _images(post: dict) -> list[str]:
        soup = BeautifulSoup(post["content"]["rendered"], "html.parser")
        urls = [urljoin(post["link"], img["src"]) for img in soup.find_all("img", src=True)
                if urlsplit(img["src"]).scheme in ("", "http", "https")]
        return list(dict.fromkeys(urls))

    @classmethod
    def _reported_count(cls, post: dict) -> int:
        title = BeautifulSoup(post["title"]["rendered"], "html.parser").get_text()
        match = cls._COUNT.search(title)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _title(post: dict) -> str:
        return normalize_title(BeautifulSoup(post["title"]["rendered"], "html.parser").get_text())

    @staticmethod
    def _tags(post: dict) -> list[str]:
        return list(dict.fromkeys(
            term["name"] for group in post.get("_embedded", {}).get("wp:term", [])
            for term in group if term.get("name")
        ))

    async def search(self, query: str, page: int, sort: str = "date") -> SearchResult:
        if sort != "date":
            raise ValueError("4KHD 仅支持按最新文章排序")
        async with self._client() as client:
            try:
                response = await retry_get(client, self._API, params={
                    "search": query, "page": page, "per_page": 20,
                    "orderby": "date", "order": "desc", "_embed": "wp:term",
                })
            except httpx.HTTPStatusError as error:
                if error.response.status_code == 400 and error.response.json().get(
                    "code"
                ) == "rest_post_invalid_page_number":
                    return SearchResult(current_page=page)
                raise
        items = []
        for post in response.json():
            if post["content"].get("protected"):
                continue
            images = self._images(post)
            if not images:
                continue
            items.append(GallerySummary(
                native_id=str(post["id"]), title=self._title(post), cover_url=images[0],
                web_url=post["link"], page_count=self._reported_count(post) or len(images),
                upload_date=post["date"], tags=self._tags(post),
            ))
        return SearchResult(items=items,
                            total_pages=int(response.headers.get("X-WP-TotalPages", 0)),
                            current_page=page)

    def _parse_gallery_response(self, post: dict) -> GalleryDetail:
        if post["content"].get("protected"):
            raise ValueError("4KHD 图集未公开，无法下载")
        images = self._images(post)
        expected = self._reported_count(post)
        if not images:
            raise ValueError("4KHD 图集没有公开图片，无法下载")
        warning = ""
        if len(images) < expected:
            warning = (f"4KHD 图集图片不完整：标注 {expected} 张，公开 {len(images)} 张"
                       f"（少 {expected - len(images)} 张）。")
        return GalleryDetail(
            native_id=str(post["id"]), title=self._title(post), cover_url=images[0],
            web_url=post["link"], page_urls=images, reported_pages=len(images),
            page_native_ids=[hashlib.sha256(url.encode()).hexdigest()[:16] for url in images],
            upload_date=post["date"], tags=self._tags(post),
            num_favorites=None,
            warning=warning,
        )

    async def get_gallery(self, gallery_id: str, gallery_url: str = "") -> GalleryDetail:
        if not gallery_id.isdecimal():
            raise ValueError("4KHD 图集 ID 应为文章数字 ID")
        async with self._client() as client:
            response = await retry_get(client, f"{self._API}/{int(gallery_id)}",
                                       params={"_embed": "wp:term"})
        return self._parse_gallery_response(response.json())

    async def download_pages(self, gallery_id: str, page_range: slice, gallery_url: str = "",
                             detail: GalleryDetail | None = None,
                             on_page: Callable[[], None] | None = None) -> list[bytes]:
        from comicfeed.infrastructure.config import get_setting
        retries = max(1, int(await get_setting("download_retry") or 3))
        if detail is None:
            detail = await self.get_gallery(gallery_id, gallery_url)
        pages = []
        async with self._client() as client:
            for url in detail.page_urls[page_range]:
                response = await retry_get(client, url, max_retries=retries)
                data = response.content
                try:
                    with Image.open(BytesIO(data)) as image:
                        image.verify()
                    with Image.open(BytesIO(data)) as image:
                        image.load()
                except (UnidentifiedImageError, OSError, ValueError) as error:
                    raise ValueError("4KHD 图片响应无效，未取得完整图片") from error
                pages.append(data)
                if on_page:
                    on_page()
        return pages

    async def check_updates(self, gallery_id: str, last_known: dict,
                            gallery_url: str = "") -> UpdateResult:
        return UpdateResult()

    async def test_connection(self) -> tuple[bool, str]:
        try:
            async with self._client() as client:
                response = await retry_get(client, self._API,
                                           params={"per_page": 1, "_fields": "id"})
            if not isinstance(response.json(), list):
                return False, "4KHD 文章 API 响应无效"
            return True, "4KHD 公开文章 API 连接成功"
        except Exception as error:
            return False, str(error)
