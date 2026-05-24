from comicfeed.sources.nhentai import NhentaiSource


async def test_parse_url_extracts_gallery_id():
    """从 nhentai URL 中提取 gallery ID。"""
    source = NhentaiSource()
    assert source.parse_url("https://nhentai.net/g/455819/") == "nhentai:455819"
    assert source.parse_url("https://nhentai.net/g/455819") == "nhentai:455819"
    assert source.parse_url("not-a-valid-url") is None
