import pytest

from comicfeed.sources.nhentai import NhentaiSource

# Sample data matching nhentai v2 API format
_SAMPLE_SEARCH = {
    "result": [
        {
            "id": 455819,
            "media_id": 12345,
            "title": {"english": "Sample Comic", "japanese": None, "pretty": "Sample Comic"},
            "thumbnail": "/galleries/12345/cover.jpg",
            "thumbnail_width": 350,
            "thumbnail_height": 500,
            "english_title": "Sample Comic",
            "japanese_title": None,
            "tag_ids": [123, 456],
            "num_pages": 32,
        },
        {
            "id": 455820,
            "media_id": 12346,
            "title": {"english": "Another", "japanese": "日本語", "pretty": "Another"},
            "thumbnail": "/galleries/12346/cover.jpg",
            "thumbnail_width": 350,
            "thumbnail_height": 500,
            "english_title": "Another",
            "japanese_title": "日本語",
            "tag_ids": [789],
            "num_pages": 16,
        },
    ],
    "num_pages": 1,
    "per_page": 25,
}

_SAMPLE_GALLERY = {
    "id": 455819,
    "media_id": 12345,
    "title": {"english": "Sample Comic", "japanese": None, "pretty": "Sample Comic"},
    "cover": {"path": "/galleries/12345/cover.jpg", "width": 350, "height": 500},
    "thumbnail": {"path": "/galleries/12345/thumb.jpg", "width": 200, "height": 280},
    "scanlator": "",
    "upload_date": 1700000000,
    "tags": [
        {"id": 123, "name": "full color", "count": 1000, "type": "tag", "url": "/tag/..."},
        {"id": 456, "name": "big breasts", "count": 5000, "type": "tag", "url": "/tag/..."},
    ],
    "num_pages": 2,
    "num_favorites": 100,
    "pages": [
        {"number": 1, "path": "/galleries/12345/1.jpg", "width": 1280, "height": 1800,
         "thumbnail": "/galleries/12345/1t.jpg", "thumbnail_width": 150, "thumbnail_height": 210},
        {"number": 2, "path": "/galleries/12345/2.jpg", "width": 1280, "height": 1800,
         "thumbnail": "/galleries/12345/2t.jpg", "thumbnail_width": 150, "thumbnail_height": 210},
    ],
}


async def test_parse_url_extracts_gallery_id():
    """从 nhentai URL 中提取 gallery ID。"""
    source = NhentaiSource()
    assert source.parse_url("https://nhentai.net/g/455819/") == "nhentai:455819"
    assert source.parse_url("https://nhentai.net/g/455819") == "nhentai:455819"
    assert source.parse_url("not-a-valid-url") is None


def test_parse_search_response():
    """解析 v2 API 搜索响应 JSON。"""
    source = NhentaiSource()
    result = source._parse_search_response(_SAMPLE_SEARCH, page=1)
    assert result.current_page == 1
    assert result.total_pages == 1
    assert len(result.items) == 2
    assert result.items[0].native_id == "455819"
    assert result.items[0].title == "Sample Comic"
    assert result.items[0].cover_url == "https://t.nhentai.net/galleries/12345/cover.jpg"
    assert result.items[0].page_count == 32


def test_parse_gallery_response():
    """解析 v2 API 画廊详情响应 JSON。"""
    source = NhentaiSource()
    detail = source._parse_gallery_response(_SAMPLE_GALLERY)
    assert detail.native_id == "455819"
    assert detail.title == "Sample Comic"
    assert detail.cover_url == "https://t.nhentai.net/galleries/12345/cover.jpg"
    assert len(detail.tags) == 2
    assert "full color" in detail.tags
    assert detail.reported_pages == 2
    assert len(detail.page_urls) == 2
    assert detail.page_urls[0] == "https://i.nhentai.net/galleries/12345/1.jpg"


@pytest.mark.integration
@pytest.mark.skip(reason="需要 cf_clearance cookie 绕过 Cloudflare")
async def test_search_returns_results():
    """搜索返回 GallerySummary 列表（需要 cf_clearance cookie）。"""
    source = NhentaiSource(proxy="http://localhost:8889")
    result = await source.search("tag:full_color", page=1)
    assert len(result.items) > 0
    assert result.current_page == 1
    first = result.items[0]
    assert first.native_id
    assert first.title
    assert first.cover_url
    assert first.page_count > 0
