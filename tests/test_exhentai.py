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
  <td class="gl1c glcat"></td>
  <td class="gl2c" style="background:url(https://s.exhentai.org/g/1234567/abc1/cover.jpg) -32px -64px"></td>
  <td class="gl3c glname"><a href="https://exhentai.org/g/1234567/aabbcc11/">Test Gallery Title</a></td>
  <td class="gl4c glhide">Uploader · 32 pages</td>
</tr>
<tr>
  <td class="gl1c glcat"></td>
  <td class="gl2c"></td>
  <td class="gl3c glname"><a href="https://exhentai.org/g/7654321/bbccdd22/">Another Gallery</a></td>
  <td class="gl4c glhide">Uploader2 · 16 pages</td>
</tr>
</table>
"""


def test_parse_search_html():
    """解析搜索页面 HTML 返回 GallerySummary。"""
    s = ExhentaiSource()
    result = s._parse_search_html(_SAMPLE_SEARCH_HTML, page=0)
    assert len(result.items) == 2
    assert result.items[0].native_id == "1234567"
    assert result.items[0].title == "Test Gallery Title"
    assert "ehgt.org" in result.items[0].cover_url
    assert result.items[0].page_count == 32
    assert result.items[0].web_url  # web_url 非空
    # 无封面的行构造占位 URL
    assert result.items[1].page_count == 16
    assert "ehgt.org" in result.items[1].cover_url


_SAMPLE_GALLERY_HTML = """
<html><body>
<div id="gd2"><p>You are currently viewing a-2024-12-31 20:00</p></div>
<h1 id="gn">Gallery Title</h1>
<h1 id="gj">Japanese Title</h1>
<div id="gleft"><div id="gd1"><div style="background:url(https://ehgt.org/g/1234567/cover.jpg)"></div></div></div>
<div id="gdd"><table><tbody>
<tr><td class="gdt1">Posted:</td><td class="gdt2">2024-12-31 20:00</td></tr>
<tr><td class="gdt1">Favorited:</td><td class="gdt2">123 times</td></tr>
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
    assert "artist name" in " ".join(d.tags)
    assert "tag1" in " ".join(d.tags)
    assert d.reported_pages == 34
    assert len(d.page_urls) > 0  # 从缩略图链接构造
    assert "exhentai.org/g/1234567/aabbcc11" in d.web_url
