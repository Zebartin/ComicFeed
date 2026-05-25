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
                params={"f_search": query, "page": page, "inline_set": "dm_e"},
            )
            resp.raise_for_status()
            # with open(f"debug_exh_search_{page}.html", "w", encoding="utf-8") as f:
            #     f.write(resp.text)
            return self._parse_search_html(resp.text, page)

    def _parse_search_html(self, html: str, page: int) -> SearchResult:
        soup = BeautifulSoup(html, "lxml")
        items = []
        for row in soup.select("tr"):
            gl1e = row.select_one("td.gl1e")
            gl2e = row.select_one("td.gl2e")
            if not gl1e or not gl2e:
                continue

            # 封面图
            cover = ""
            img = gl1e.select_one("img")
            if img:
                cover = img.get("src", "")
                if "ehgt.org" not in cover and cover:
                    cover = cover.replace("ehgt.org", cover.split("/")[2]) if "/" in cover else cover
                    cover = cover if "ehgt.org" in cover else f"https://ehgt.org{cover}" if cover.startswith("/") else cover
            cover = cover.replace("s.exhentai.org", "ehgt.org")

            # Gallery 链接和 ID
            gid = ""
            token = ""
            for a in gl2e.select("a"):
                m = self._GALLERY_LINK.search(a.get("href", ""))
                if m:
                    gid = m.group(1)
                    token = m.group(2)
                    break
            if not gid:
                continue

            # 标题：取 gl2e 中非元数据的最长 div 文本
            title = ""
            candidates = []
            for d in gl2e.select("div:not(.gt)"):
                t = d.get_text(strip=True)
                if not t:
                    continue
                low = t.lower()
                # 跳过元数据行
                if re.match(r"^\d{4}-\d{2}-\d{2}", t):  # 日期
                    continue
                if re.match(r"^\d+\s*pages?", low):  # 页数
                    continue
                if t in ("Doujinshi", "Manga", "Artist CG", "Game CG", "Western", "Non-H", "Image Set", "Cosplay", "Asian Porn", "Misc"):
                    continue
                if any(ns in low for ns in ["language:", "parody:", "character:", "artist:", "group:", "female:", "male:"]):
                    continue
                candidates.append(t)
            if candidates:
                title = max(candidates, key=len)

            # 页数：逐 div 查找，避免文本拼接干扰
            pg_count = 0
            for d in gl2e.select("div"):
                m_pg = re.search(r"(\d+)\s*pages?", d.get_text(strip=True), re.IGNORECASE)
                if m_pg:
                    pg_count = int(m_pg.group(1))
                    break

            # 标签：td.tc + 紧邻的 td 成对解析
            tag_names = []
            tds = row.select("td")
            from comicfeed.tag_translator import get_translator
            _tt = get_translator()
            for i, td in enumerate(tds):
                if "tc" in (td.get("class") or []):
                    ns = td.get_text(strip=True).rstrip(":")
                    # 下一个 td 中的 div 是标签值
                    next_td = tds[i + 1] if i + 1 < len(tds) else None
                    if next_td:
                        for d in next_td.select("div"):
                            name = d.get_text(strip=True)
                            if name and ns:
                                tag_names.append(_tt.translate(ns, name))

            web = f"https://e-hentai.org/g/{gid}/{token}/"
            items.append(GallerySummary(
                native_id=gid,
                title=title,
                cover_url=cover,
                web_url=web,
                page_count=pg_count,
                tags=tag_names,
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
