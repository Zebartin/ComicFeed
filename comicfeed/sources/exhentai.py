import asyncio
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

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

from comicfeed.infrastructure import gallery_cache as _gc


class ExhentaiSource(BaseSource):
    key = "exhentai"
    name = "ExHentai"
    version = "0.1.0"
    domains = ["exhentai.org", "e-hentai.org"]
    auth_schema = AuthSchema.COOKIE

    _URL_PATTERN = re.compile(r"https?://(?:exhentai|e-hentai)\.org/g/(\d+)/(\w+)")
    _GALLERY_LINK = re.compile(r"/g/(\d+)/(\w+)")
    _PAGE_ID = re.compile(r"/s/(\w+)/")

    def __init__(self, proxy=None, credentials=None):
        super().__init__(proxy=proxy, credentials=credentials)
        self._base = "https://exhentai.org"
        self._next_url: str = ""  # 游标制翻页

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

    @staticmethod
    def _ensure_inline_set(url: str) -> str:
        """确保 URL 中包含 inline_set=dm_e 参数。"""
        if not url:
            return url
        u = urlparse(url)
        qs = parse_qs(u.query, keep_blank_values=True)
        qs["inline_set"] = ["dm_e"]
        return urlunparse(u._replace(query=urlencode(qs, doseq=True)))

    async def search(self, query: str, page: int, sort: str = "date") -> SearchResult:
        async with self._client() as client:
            if page <= 1 and not self._next_url:
                self._next_url = ""
                url = self._ensure_inline_set(f"{self._base}/?f_search={query}&page=0")
                resp = await client.get(url)
            elif self._next_url:
                resp = await client.get(self._ensure_inline_set(self._next_url))
            else:
                url = self._ensure_inline_set(f"{self._base}/?f_search={query}&page={page}")
                resp = await client.get(url)
            resp.raise_for_status()
            result = self._parse_search_html(resp.text, page)
            self._next_url = result.next_url
            return result

    @staticmethod
    def _extract_page_id(url: str) -> str | None:
        """从 viewer URL 提取页面 ID。如 /s/cc58247135/... → cc58247135"""
        m = re.search(r"/s/(\w+)/", url)
        return m.group(1) if m else None

    @staticmethod
    def _make_thumbnail_url(path: str) -> str:
        """修改缩略图URL，使其能够正常显示。"""
        return path.replace("s.exhentai.org", "ehgt.org")

    def _parse_search_html(self, html: str, page: int) -> SearchResult:
        soup = BeautifulSoup(html, "lxml")
        items = []
        for row in soup.select("tr"):
            gl1e = row.select_one("td.gl1e")
            gl2e = row.select_one("td.gl2e")
            if not gl1e or not gl2e:
                continue

            # 封面图
            cover = self._make_thumbnail_url(gl1e.select_one("img").get("src", ""))

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

            # 标题：取 div.glink，归一化处理
            from comicfeed.cbz import normalize_title
            title = normalize_title(gl2e.select_one("div.glink").get_text(strip=True))

            # 页数：逐 div 查找，避免文本拼接干扰
            pg_count = 0
            for d in gl2e.select("div.gl3e > div"):
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

            # Web URL：select a标签，提取href
            web = row.select_one("td.gl2e > div > a").get("href", "")
            items.append(GallerySummary(
                native_id=gid,
                title=title,
                cover_url=cover,
                web_url=web,
                page_count=pg_count,
                tags=tag_names,
            ))
        # 提取下一页链接（游标制翻页）
        next_url = ""
        for a in soup.select("a"):
            if "Next" in a.get_text(strip=True):
                next_url = a.get("href", "")
                break

        return SearchResult(items=items, current_page=page, next_url=next_url)

    async def get_gallery(self, gallery_id: str, gallery_url: str = "") -> GalleryDetail:
        gurl = gallery_url or f"{self._base}/g/{gallery_id}/"

        # 检查是否有 check_updates 预过滤的 detail（一次性消耗）
        upd = _gc.update_cache_get(gallery_id)
        if upd:
            return upd

        cached = _gc.cache_get(gurl)
        if cached:
            return cached
        async with self._client() as client:
            resp = await client.get(gurl)
            resp.raise_for_status()
            detail = self._parse_gallery_html(resp.text, gallery_id)
            detail.web_url = gurl

            # 收集所有页面的 viewer URL（遍历 gallery 分页）
            if detail.page_urls:
                all_urls = list(detail.page_urls)
                all_pids = list(detail.page_native_ids)
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
                    all_pids.extend(self._extract_page_id(u) for u in more)
                    page_idx += 1
                detail.page_urls = all_urls
                detail.page_native_ids = [p for p in all_pids if p]

            _gc.cache_set(gurl, detail)
            return detail

    def _parse_gallery_html(self, html: str, gallery_id: str) -> GalleryDetail:
        soup = BeautifulSoup(html, "lxml")

        # 标题：优先日文 gj，其次英文 gn，归一化处理
        from comicfeed.cbz import normalize_title
        gj = soup.select_one("h1#gj")
        gn = soup.select_one("h1#gn")
        title = (gj.get_text(strip=True) if gj else "") or (gn.get_text(strip=True) if gn else "")
        title = normalize_title(title)

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
        writers = []
        _WRITER_NS = {"artist", "group", "画师", "团队"}
        from comicfeed.tag_translator import get_translator
        _tt = get_translator()
        for tr in soup.select("div#taglist table tr"):
            tds = tr.select("td")
            if len(tds) >= 2:
                ns = tds[0].get_text(strip=True).rstrip(":")
                for a in tds[1].select("a"):
                    name = a.get_text(strip=True)
                    if not name:
                        continue
                    if ns:
                        translated = _tt.translate(ns, name)
                        if ns.lower() in _WRITER_NS:
                            writers.append(translated)
                        else:
                            tags.append(translated)
                    else:
                        # 无 namespace：优先匹配非 writer 类型
                        translated = _tt.translate("", name, avoid_ns=_WRITER_NS)
                        tags.append(translated)

        # 上传时间
        upload_date = ""
        for tr in soup.select("div#gdd tr"):
            tds = tr.select("td")
            if len(tds) >= 2 and "posted" in tds[0].get_text().lower():
                upload_date = tds[1].get_text(strip=True)
                break

        # 页数
        reported_pages = 0
        for el in soup.select("td.gdt2, div.gdtm"):
            text = el.get_text()
            if "pages" in text:
                reported_pages = int(re.sub(r"\D", "", text) or "0")
                break
        
        # 收藏数
        num_fav = int(soup.select_one("#favcount").get_text(strip=True).split()[0])

        # 页面 URL（从当前 viewer 页的缩略图提取）
        page_urls = []
        for a in soup.select("div#gdt a"):
            href = a.get("href", "")
            if href:
                page_urls.append(href)

        page_native_ids = [self._extract_page_id(u) for u in page_urls]
        page_native_ids = [p for p in page_native_ids if p]

        return GalleryDetail(
            native_id=gallery_id,
            title=title,
            cover_url=self._make_thumbnail_url(cover_url),
            tags=tags,
            writers=writers,
            page_urls=page_urls,
            page_native_ids=page_native_ids,
            upload_date=upload_date,
            reported_pages=reported_pages,
            num_favorites=num_fav
        )

    @staticmethod
    def _extract_nl(soup: BeautifulSoup) -> str:
        """从 viewer 页面提取 nl token。"""
        el = soup.select_one("#loadfail") or soup.select_one("div#i6 a#loadfail")
        if el:
            onclick = el.get("onclick", "")
            for part in onclick.split("'"):
                if "-" in part:
                    return part
        return ""

    async def download_pages(self, gallery_id: str, page_range: slice, gallery_url: str = "", detail: GalleryDetail | None = None) -> list[bytes]:
        from comicfeed.config import get_setting
        from comicfeed.log import get
        _log = get(__name__)
        _retry = int(await get_setting("download_retry", "3") or "3")
        if detail is None:
            detail = await self.get_gallery(gallery_id, gallery_url=gallery_url)
        urls = detail.page_urls[page_range]
        results = []
        import httpx
        async with self._client() as client:
            for i, viewer_url in enumerate(urls):
                page_no = page_range.start + i + 1
                nl = ""
                last_err = None
                for attempt in range(_retry):
                    try:
                        # 访问 viewer 页（有 nl 时带上）
                        req_url = viewer_url
                        if nl:
                            sep = "&" if "?" in viewer_url else "?"
                            req_url = viewer_url + sep + "nl=" + nl
                            _log.debug("重试带 nl: %s", nl)
                        resp = await client.get(req_url)
                        resp.raise_for_status()
                        soup = BeautifulSoup(resp.text, "lxml")

                        # 提取 nl（每次访问 viewer 页都可能更新）
                        new_nl = self._extract_nl(soup)
                        if new_nl:
                            nl = new_nl
                            _log.debug("nl token: %s", nl)

                        # 提取图片 URL
                        img = soup.select_one("img#img")
                        if img:
                            img_url = img.get("src", "")
                        else:
                            imgs = soup.select("img")
                            img_url = imgs[0].get("src", "") if imgs else ""

                        if not img_url:
                            _log.warning("未找到图片: %s page=%d viewer=%s", gallery_id, page_no, viewer_url)
                            results.append(b"")
                            break

                        # 下载图片
                        try:
                            async with httpx.AsyncClient(proxy=self.proxy, timeout=30) as img_client:
                                img_resp = await img_client.get(img_url)
                                img_resp.raise_for_status()
                                results.append(img_resp.content)
                                break
                        except Exception as e:
                            _log.warning("下载图片失败(尝试%d/%d): %s page=%d nl=%s - %r",
                                        attempt + 1, _retry, gallery_id, page_no, nl, e)
                            if attempt < _retry - 1:
                                await asyncio.sleep(1)
                                # 下一轮带 nl 重访 viewer 页
                                continue
                            raise

                    except Exception as e:
                        last_err = e
                        if attempt < _retry - 1:
                            await asyncio.sleep(1)
                else:
                    _log.error("下载图片失败(重试%d次): gallery=%s page=%d viewer=%s - %r",
                               _retry, gallery_id, page_no, viewer_url, last_err)
                    raise last_err
        return results

    async def check_updates(self, gallery_id: str, last_known: dict, gallery_url: str = "") -> UpdateResult:
        """检查画廊是否有更新（newer version 跳转 + 页面 ID 对比）。"""
        old_ids: set[str] = set(last_known.get("page_ids", []))
        gid = gallery_id
        gurl = gallery_url

        async with self._client() as client:
            resp = await client.get(gurl)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            newer = soup.select_one("#gnd")
            if newer:
                all_a = newer.select("a")
                href = all_a[-1].get("href", "")
                m = self._GALLERY_LINK.search(href)
                if m:
                    gid = m.group(1)
                    gurl = href
            elif old_ids:
                return UpdateResult()

        # 解析完整 page ID 列表
        detail = await self.get_gallery(gid, gurl)
        current_ids = set(detail.page_native_ids)
        new_ids = current_ids - old_ids
        if new_ids:
            keep_idx = [i for i, pid in enumerate(detail.page_native_ids) if pid in new_ids]
            filtered = GalleryDetail(
                native_id=detail.native_id,
                title=detail.title,
                cover_url=detail.cover_url,
                web_url=gurl,
                page_urls=[detail.page_urls[i] for i in keep_idx],
                page_native_ids=[detail.page_native_ids[i] for i in keep_idx],
                tags=list(detail.tags),
                writers=list(detail.writers),
                upload_date=detail.upload_date,
                reported_pages=len(keep_idx),
                num_favorites=detail.num_favorites,
            )
            _gc.update_cache_set(gid, filtered)
            return UpdateResult(has_updates=True, gallery=GallerySummary(
                native_id=gid,
                title=detail.title,
                cover_url=detail.cover_url,
                web_url=gurl,
                page_count=len(new_ids),
                tags=detail.tags,
                new_page_ids=list(new_ids),
                replaces_native_id=gallery_id if gid != gallery_id else "",
                detail=filtered,
            ))
        return UpdateResult()
