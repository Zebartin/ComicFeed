from comicfeed.sources.exhentai import ExhentaiSource


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
    assert len(d.page_urls) > 0  # 从缩略图链接构造
    # web_url 由 get_gallery 异步方法设置，_parse_gallery_html 返回时为空
