from types import SimpleNamespace

import pytest

from comicfeed.sources.base import GalleryDetail
from comicfeed.sources.exhentai import ExHentaiAuthError, ExhentaiSource, _cookie_failure


def test_parse_url():
    """从 e-hentai/exhentai URL 提取 gallery ID。"""
    s = ExhentaiSource()
    assert s.parse_url("https://exhentai.org/g/1234567/abc123def/") == "exhentai:1234567"
    assert s.parse_url("https://exhentai.org/g/1234567/abc123def") == "exhentai:1234567"
    assert s.parse_url("https://e-hentai.org/g/1234567/abc123def/") == "exhentai:1234567"
    assert s.parse_url("https://nhentai.net/g/123/") is None
    assert s.parse_url("not a url") is None


_SAMPLE_SEARCH_HTML = """
<table class="itg">
<tr>
  <td class="gl1e"><img src="https://ehgt.org/g/1234567/abc1/cover.jpg"/></td>
  <td class="gl2e">
    <div><a href="https://exhentai.org/g/1234567/aabbcc11/">artist</a></div>
    <div>Doujinshi</div><div class="gl3e"><div>2026-05-25 10:55</div><div>32 pages</div></div>
    <div class="glink"><a href="/g/1234567/aabbcc11/">Test Gallery Title</a></div>
    <div class="gt">language:</div><div class="gtl"><div>chinese</div><div>translated</div></div>
  </td>
  <td class="tc">language:</td><td><div>chinese</div><div>translated</div></td>
  <td class="tc">artist:</td><td><div>ryukisakuya</div></td>
</tr>
<tr>
  <td class="gl1e"><img src="https://ehgt.org/g/7654321/bbcc/cover.jpg"/></td>
  <td class="gl2e">
    <div><a href="https://exhentai.org/g/7654321/bbccdd22/">artist2</a></div>
    <div>Manga</div><div class="gl3e"><div>2026-05-24</div><div>16 pages</div></div>
    <div class="glink"><a href="/g/7654321/bbccdd22/">Another Gallery</a></div>
    <div class="gt">language:</div><div class="gtl"><div>english</div></div>
  </td>
  <td class="tc">language:</td><td><div>english</div></td>
</tr>
</table>
"""


def test_parse_search_html():
    """解析扩展模式搜索页面 HTML。"""
    s = ExhentaiSource()
    result = s._parse_search_html(_SAMPLE_SEARCH_HTML, page=0)
    assert len(result.items) == 2
    assert result.items[0].native_id == "1234567"
    assert result.items[0].title == "Test Gallery Title"
    assert "ehgt.org" in result.items[0].cover_url
    assert result.items[0].page_count == 32
    assert "/g/1234567/" in result.items[0].web_url
    assert len(result.items[0].tags) >= 2
    assert result.items[1].page_count == 16


_SAMPLE_GALLERY_HTML = """
<html><body>
<div id="gd2"><p>You are currently viewing a-2024-12-31 20:00</p></div>
<h1 id="gn">Gallery Title</h1>
<h1 id="gj">Japanese Title</h1>
<div id="gleft"><div id="gd1"><div style="background:url(https://ehgt.org/g/1234567/cover.jpg)"></div></div></div>
<div id="gdd"><table><tbody>
<tr><td class="gdt1">Posted:</td><td class="gdt2">2024-12-31 20:00</td></tr>
<tr><td class="gdt1">Favorited:</td><td class="gdt2"><span id="favcount">123</span> times</td></tr>
</tbody></table></div>
<div id="taglist"><table><tbody>
<tr><td class="tc">artist:</td><td><div><a>artist name</a></div></td></tr>
<tr><td class="tc">female:</td><td><div><a>tag1</a></div></td></tr>
</tbody></table></div>
<div id="gdt"><a href="https://exhentai.org/g/1234567/aabbcc11/?p=0"><img src="https://ehgt.org/t/page1.jpg" /></a></div>
<div class="gdtm">34 pages</div>
<div class="sn"><span>&laquo; Newer Version</span></div>
</body></html>
"""


def test_parse_gallery_html():
    """解析画廊详情页 HTML。"""
    s = ExhentaiSource()
    d = s._parse_gallery_html(_SAMPLE_GALLERY_HTML, "1234567")
    assert d.native_id == "1234567"
    assert d.title == "Japanese Title"  # japanese_title preferred
    assert "cover" in d.cover_url
    assert "artist name" in " ".join(d.writers)
    assert "tag1" in " ".join(d.tags)
    assert d.reported_pages == 34
    assert d.num_favorites == 123
    assert len(d.page_urls) > 0  # 从缩略图链接构造
    # web_url 由 get_gallery 异步方法设置，_parse_gallery_html 返回时为空


def test_parse_gallery_html_missing_favcount():
    """favcount 缺失或为空时不抛异常，收藏数默认为 0。"""
    s = ExhentaiSource()
    html = _SAMPLE_GALLERY_HTML.replace('<span id="favcount">123</span>', "")
    d = s._parse_gallery_html(html, "1234567")
    assert d.num_favorites == 0
    # 元素存在但为空
    html_empty = _SAMPLE_GALLERY_HTML.replace('<span id="favcount">123</span>', '<span id="favcount"></span>')
    d2 = s._parse_gallery_html(html_empty, "1234567")
    assert d2.num_favorites == 0


# --- Cookie 失效 / IP 限制检测 ---


class _FakeResponse(SimpleNamespace):
    """带 raise_for_status 的假响应（retry_get 依赖它）。"""

    def raise_for_status(self):
        pass


def _resp(url: str = "https://exhentai.org/s/abc/1-1/", status_code: int = 200, text: str = ""):
    return _FakeResponse(url=url, status_code=status_code, text=text)


_SAD_PANDA_HTML = '<html><body><div id="sadpanda"><img src="https://exhentai.org/img/sadpanda.png"></div></body></html>'


def test_cookie_failure_detects_sad_panda_redirect_url():
    """Cookie 失效：请求被重定向到 sadpanda.php。"""
    assert _cookie_failure(_resp(url="https://exhentai.org/sadpanda.php")) is not None


def test_cookie_failure_detects_sad_panda_html():
    """Cookie 失效：页面内容为 Sad Panda 页。"""
    assert _cookie_failure(_resp(text=_SAD_PANDA_HTML)) is not None


def test_cookie_failure_detects_http_403():
    """403：Cookie 失效或 IP 被限制。"""
    assert _cookie_failure(_resp(status_code=403)) is not None


def test_cookie_failure_detects_empty_response():
    """Cookie 失效还可能返回 200 空 body，不能静默当成功。"""
    assert _cookie_failure(_resp(text="")) is not None
    assert _cookie_failure(_resp(text="   \n  ")) is not None


def test_cookie_failure_detects_forums_redirect():
    """未登录访问被重定向到 e-hentai 论坛登录页。"""
    assert _cookie_failure(_resp(url="https://forums.e-hentai.org/index.php")) is not None


def test_cookie_failure_detects_ip_banned():
    """IP 被封禁文案。"""
    assert _cookie_failure(_resp(text="Your IP address has been banned.")) is not None


def test_cookie_failure_ok_on_normal_page():
    """正常页面不误报。"""
    assert _cookie_failure(_resp(text=_SAMPLE_GALLERY_HTML)) is None


class _FakeClient:
    """返回固定响应的假 HTTP client（async context manager）。"""

    def __init__(self, resp):
        self._resp = resp
        self.calls = 0

    async def get(self, url, **kw):
        self.calls += 1
        return self._resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass


@pytest.fixture(autouse=True)
async def _db():
    """download_pages 读取 download_retry 设置，需要 DB。"""
    from comicfeed.infrastructure.database import create_tables, init_db
    init_db(":memory:")
    await create_tables()
    yield


async def test_get_gallery_raises_on_sad_panda(monkeypatch):
    """Cookie 失效时获取画廊详情直接报错，而不是解析出空画廊。"""
    s = ExhentaiSource()
    fake = _FakeClient(_resp(text=_SAD_PANDA_HTML))
    monkeypatch.setattr(s, "_client", lambda: fake)
    with pytest.raises(ExHentaiAuthError, match="Cookie"):
        await s.get_gallery("1234567")
    assert fake.calls == 1


async def test_download_pages_raises_on_sad_panda_without_retry(monkeypatch):
    """viewer 页跳 Sad Panda 时报错且不重试（Cookie 问题重试无意义）。"""
    s = ExhentaiSource()
    fake = _FakeClient(_resp(url="https://exhentai.org/sadpanda.php"))
    monkeypatch.setattr(s, "_client", lambda: fake)
    detail = GalleryDetail(native_id="1", title="T", cover_url="",
                           page_urls=["https://exhentai.org/s/abc/1-1/"],
                           page_native_ids=["abc"], reported_pages=1)
    with pytest.raises(ExHentaiAuthError, match="Cookie"):
        await s.download_pages("1", slice(0, 1), detail=detail)
    assert fake.calls == 1  # 即使 download_retry > 1 也只请求一次


async def test_download_pages_raises_on_empty_viewer_response(monkeypatch):
    """viewer 页返回空 body 时报错且不重试，而不是把空页当成功。"""
    s = ExhentaiSource()
    fake = _FakeClient(_resp(text=""))
    monkeypatch.setattr(s, "_client", lambda: fake)
    detail = GalleryDetail(native_id="1", title="T", cover_url="",
                           page_urls=["https://exhentai.org/s/abc/1-1/"],
                           page_native_ids=["abc"], reported_pages=1)
    with pytest.raises(ExHentaiAuthError, match="响应为空"):
        await s.download_pages("1", slice(0, 1), detail=detail)
    assert fake.calls == 1


async def test_download_pages_raises_when_image_is_panda(monkeypatch):
    """viewer 页无标记但图片 URL 指向熊猫图时也报错。"""
    s = ExhentaiSource()
    html = '<html><body><img src="https://exhentai.org/img/sadpanda.png"></body></html>'
    fake = _FakeClient(_resp(text=html))
    monkeypatch.setattr(s, "_client", lambda: fake)
    detail = GalleryDetail(native_id="1", title="T", cover_url="",
                           page_urls=["https://exhentai.org/s/abc/1-1/"],
                           page_native_ids=["abc"], reported_pages=1)
    with pytest.raises(ExHentaiAuthError, match="Sad Panda"):
        await s.download_pages("1", slice(0, 1), detail=detail)
