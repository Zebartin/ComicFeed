import re

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

from comicfeed.sources.base import (
    AuthSchema,
    BaseSource,
    GalleryDetail,
    GallerySummary,
    SearchResult,
    UpdateResult,
)


class ExhentaiSource(BaseSource):
    key = "exhentai"
    name = "ExHentai"
    version = "0.1.0"
    domains = ["exhentai.org", "e-hentai.org"]
    auth_schema = AuthSchema.COOKIE

    _URL_PATTERN = re.compile(r"https?://(?:exhentai|e-hentai)\.org/g/(\d+)/(\w+)")
    _GALLERY_LINK = re.compile(r"/g/(\d+)/(\w+)")

    def __init__(self, proxy=None, credentials=None):
        super().__init__(proxy=proxy, credentials=credentials)
        self._base = "https://exhentai.org"

    def get_config_schema(self) -> list[dict]:
        return [
            {"key": "proxy", "label": "代理", "type": "text", "placeholder": "空=全局, -=直连", "hint": "留空沿用全局代理"},
            {"key": "ipb_member_id", "label": "ipb_member_id", "type": "text", "credential": True, "placeholder": "从浏览器 Cookie 中获取"},
            {"key": "ipb_pass_hash", "label": "ipb_pass_hash", "type": "text", "credential": True, "placeholder": "从浏览器 Cookie 中获取"},
            {"key": "igneous", "label": "igneous", "type": "text", "credential": True, "placeholder": "从浏览器 Cookie 中获取"},
        ]

    def parse_url(self, url: str) -> str | None:
        m = self._URL_PATTERN.match(url)
        if m:
            return f"exhentai:{m.group(1)}"
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
                f"{self._base}/",
                params={"f_search": query, "page": page},
            )
            resp.raise_for_status()
            return self._parse_search_html(resp.text, page)

    def _parse_search_html(self, html: str, page: int) -> SearchResult:
        soup = BeautifulSoup(html, "lxml")
        items = []
        for row in soup.select("tr"):
            link = row.select_one("td.glname a, td.gl3c a")
            if not link:
                continue
            href = link.get("href", "")
            m = self._GALLERY_LINK.search(href)
            if not m:
                continue
            # 标题取 div.glink 文本，不取整个 a（避免 tag 混入）
            glink = link.select_one("div.glink")
            title = glink.get_text(strip=True) if glink else link.get_text(strip=True)

            # 标签：第二个 div 的文本（可能需要按命名空间解析）
            tag_divs = link.select("div:not(.glink)")
            tag_text = " ".join(d.get_text(strip=True) for d in tag_divs)

            # 封面：找 img 或 CSS background-image
            cover = ""
            img = row.select_one("img")
            if img:
                cover = img.get("src", "")
            # 如果是 CSS background，尝试从 style 提取
            if not cover:
                for td in row.select("td"):
                    style = td.get("style", "")
                    bg = re.search(r"url\(([^)]+)\)", style)
                    if bg:
                        cover = bg.group(1)
                        break
            # 替换不可直连的 CDN 域名
            cover = cover.replace("s.exhentai.org", "ehgt.org")
            # 无封面时构造占位 URL
            if not cover:
                cover = f"https://ehgt.org/g/{m.group(1)}/{m.group(2)[:4]}.jpg"

            # 页数：从同行的 gld4/gld5/gld6 或文本中找
            pg_count = 0
            for td in row.select("td"):
                text = td.get_text()
                m2 = re.search(r"(\d+)\s*pages?", text, re.IGNORECASE)
                if m2:
                    pg_count = int(m2.group(1))
                    break

            web = href if href.startswith("http") else f"https://e-hentai.org{href}"
            items.append(GallerySummary(
                native_id=m.group(1),
                title=title,
                cover_url=cover,
                web_url=web,
                page_count=pg_count,
            ))
        return SearchResult(items=items, current_page=page)

    async def get_gallery(self, gallery_id: str) -> GalleryDetail:
        gurl = await self._get_gallery_url(gallery_id)
        async with self._client() as client:
            resp = await client.get(gurl)
            resp.raise_for_status()
            detail = self._parse_gallery_html(resp.text, gallery_id)

            # 收集所有页面的 viewer URL（遍历 gallery 分页）
            if detail.page_urls:
                all_urls = list(detail.page_urls)
                page_idx = 1
                while len(all_urls) < detail.reported_pages:
                    paged_url = gurl.rstrip("/") + f"?p={page_idx}"
                    r = await client.get(paged_url)
                    r.raise_for_status()
                    soup = BeautifulSoup(r.text, "lxml")
                    more = [a.get("href", "") for a in soup.select("div#gdt a") if a.get("href")]
                    if not more:
                        break
                    all_urls.extend(more)
                    page_idx += 1
                detail.page_urls = all_urls

            return detail

    async def _get_gallery_url(self, gallery_id: str) -> str:
        """通过搜索找到 gallery 的完整 URL（含 token）。"""
        async with self._client() as client:
            resp = await client.get(
                f"{self._base}/",
                params={"f_search": f"gid:{gallery_id}", "page": 0},
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            for a in soup.select("td.gl3c a, td.glname a"):
                href = a.get("href", "")
                m = self._GALLERY_LINK.search(href)
                if m and m.group(1) == gallery_id:
                    return href
            return f"{self._base}/g/{gallery_id}/"

    def _parse_gallery_html(self, html: str, gallery_id: str) -> GalleryDetail:
        soup = BeautifulSoup(html, "lxml")
        web_url = ""

        # 标题：优先日文 gj，其次英文 gn
        gj = soup.select_one("h1#gj")
        gn = soup.select_one("h1#gn")
        title = (gj.get_text(strip=True) if gj else "") or (gn.get_text(strip=True) if gn else "")

        # 封面图
        cover_url = ""
        gleft = soup.select_one("div#gd1 div")
        if gleft:
            style = gleft.get("style", "")
            m = re.search(r"url\(([^)]+)\)", style)
            if m:
                cover_url = m.group(1)

        # 标签
        tags = []
        from comicfeed.tag_translator import get_translator
        _tt = get_translator()
        for tr in soup.select("div#taglist table tr"):
            tds = tr.select("td")
            if len(tds) >= 2:
                ns = tds[0].get_text(strip=True).rstrip(":")
                for a in tds[1].select("a"):
                    name = a.get_text(strip=True)
                    if ns and name:
                        tags.append(_tt.translate(ns, name))
                    elif name:
                        tags.append(name)

        # 页数
        reported_pages = 0
        for el in soup.select("td.gdt2, div.gdtm"):
            text = el.get_text()
            if "pages" in text:
                reported_pages = int(re.sub(r"\D", "", text) or "0")
                break

        # 页面 URL（从当前 viewer 页的缩略图提取）
        page_urls = []
        for a in soup.select("div#gdt a"):
            href = a.get("href", "")
            if href:
                page_urls.append(href)

        # web_url 用于后续翻页

        # 获取 gallery URL
        for a in soup.select("h1#gn a"):
            web_url = a.get("href", "")
            if web_url:
                break
        if not web_url:
            for a in soup.select("a"):
                m = self._GALLERY_LINK.search(a.get("href", ""))
                if m and m.group(1) == gallery_id:
                    web_url = a.get("href", "")
                    break

        return GalleryDetail(
            native_id=gallery_id,
            title=title,
            cover_url=cover_url,
            web_url=web_url,
            tags=tags,
            page_urls=page_urls,
            reported_pages=reported_pages,
        )

    async def download_pages(self, gallery_id: str, page_range: slice) -> list[bytes]:
        detail = await self.get_gallery(gallery_id)
        urls = detail.page_urls[page_range]
        results = []
        async with self._client() as client:
            for viewer_url in urls:
                resp = await client.get(viewer_url)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")
                img = soup.select_one("img#img")
                if img:
                    img_url = img.get("src", "")
                else:
                    # fallback: look for any large image
                    imgs = soup.select("img")
                    img_url = imgs[0].get("src", "") if imgs else ""
                if img_url:
                    img_resp = await client.get(img_url)
                    img_resp.raise_for_status()
                    results.append(img_resp.content)
                else:
                    results.append(b"")
        return results

    async def check_updates(self, gallery_id: str, last_known: dict) -> UpdateResult:
        """检查画廊是否有更新版本。"""
        gurl = await self._get_gallery_url(gallery_id)
        async with self._client() as client:
            resp = await client.get(gurl)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            newer = soup.select_one("div.sn a, div.sn span")
            if newer and "newer" in newer.get_text().lower():
                href = newer.get("href", "") if newer.name == "a" else ""
                m = self._GALLERY_LINK.search(href)
                if m:
                    return UpdateResult(has_updates=True, new_gallery_id=m.group(1))
        return UpdateResult()
