from comicfeed.sources.exhentai import ExhentaiSource


def test_extract_page_id():
    """从 exhentai viewer URL 提取页面 ID。"""
    s = ExhentaiSource()
    url = "https://exhentai.org/s/cc58247135/3952901-7"
    assert s._extract_page_id(url) == "cc58247135"

    # e-hentai 同样格式
    assert s._extract_page_id("https://e-hentai.org/s/abc123/123-1") == "abc123"

    # 无效 URL
    assert s._extract_page_id("https://nhentai.net/g/123/") is None
    assert s._extract_page_id("") is None


def test_parse_gallery_extracts_page_ids():
    """解析画廊 HTML 时提取页面 ID。"""
    s = ExhentaiSource()
    html = """
    <div id="gdd"><table><tr><td class="gdt1">Favorited:</td><td class="gdt2"><span id="favcount">456</span> times</td></tr></table></div>
    <div id="gdt">
      <a href="https://exhentai.org/s/aa11bb22/123-1"><img src="t.jpg"/></a>
      <a href="https://exhentai.org/s/cc33dd44/123-2"><img src="t.jpg"/></a>
      <a href="https://exhentai.org/s/ee55ff66/123-3"><img src="t.jpg"/></a>
    </div>
    <div class="gdtm">3 pages</div>
    """
    d = s._parse_gallery_html(html, "123")
    assert d.page_native_ids == ["aa11bb22", "cc33dd44", "ee55ff66"]
    assert len(d.page_urls) == 3
