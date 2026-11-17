from copy import deepcopy
from io import BytesIO
import json
from unittest.mock import AsyncMock
from zipfile import ZipFile

import httpx
import pytest
from PIL import Image

from comicfeed.infrastructure.source_manager import SourceManager
from comicfeed.services.download import download_gallery
from comicfeed.sources.fourkhd import FourKHDSource


_FIRST = "https://i0.wp.com/pic.4khd.com/sample-001.webp?w=1300"
_LAST = "https://i0.wp.com/pic.4khd.com/sample-002.webp?w=1300"
_PAGE = "https://www.4khd.com/content/12/sample.html"
_POST = {
    "id": 42,
    "title": {"rendered": "测试图集 &#8211; 样本[12MB-2photos]"},
    "date": "2026-11-12T18:27:00",
    "link": _PAGE,
    "content": {
        "protected": False,
        "rendered": f'<img src="{_FIRST}"><!--nextpage-->'
                    f'<img src="{_FIRST}"><img src="{_LAST}">',
    },
    "_embedded": {"wp:term": [[{"name": "cosplay"}], [{"name": "cosplay"}]]},
}


@pytest.fixture
def media():
    first, last = BytesIO(), BytesIO()
    Image.new("RGB", (200, 300), "blue").save(first, "JPEG")
    # 小尺寸尾页会被现有广告检测剔除，4KHD 必须保留。
    Image.new("RGB", (12, 12), "red").save(last, "WEBP")
    return {_FIRST: first.getvalue(), _LAST: last.getvalue()}


@pytest.fixture
def source(media, monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/content/12/sample.html":
            return httpx.Response(200, text=
                '<link type="application/json" href="/wp-json/oembed/1.0/embed">'
                '<link type="application/json" href="/wp-json/wp/v2/posts/42">')
        if request.url.path == "/wp-json/wp/v2/posts/42":
            return httpx.Response(200, json=_POST)
        if request.url.path == "/wp-json/wp/v2/posts":
            if request.url.params.get("page") == "4":
                return httpx.Response(400, json={"code": "rest_post_invalid_page_number"})
            return httpx.Response(200, json=[_POST], headers={"X-WP-TotalPages": "3"})
        if str(request.url) in media:
            return httpx.Response(200, content=media[str(request.url)])
        return httpx.Response(404)

    async def get_setting(key):
        assert key == "download_retry"
        return "3"

    monkeypatch.setattr("comicfeed.infrastructure.config.get_setting", get_setting)
    instance = FourKHDSource(transport=httpx.MockTransport(handler))
    return instance, requests


def test_plugin_is_loaded():
    from pathlib import Path
    manager = SourceManager()
    keys = manager.load_sources(str(Path(__file__).parents[1] / "comicfeed" / "sources"))
    assert "4khd" in keys
    assert manager.get_source("4khd").remove_ads is False


async def test_search_preserves_query_and_pagination(source):
    instance, requests = source
    result = await instance.search("Machi馬吉", page=2)
    assert requests[-1].url.params["search"] == "Machi馬吉"
    assert requests[-1].url.params["page"] == "2"
    assert requests[-1].url.params["order"] == "desc"
    assert result.current_page == 2 and result.total_pages == 3
    gallery = result.items[0]
    assert gallery.native_id == "42" and gallery.page_count == 2
    assert gallery.title == "测试图集 – 样本[12MB-2photos]"
    assert gallery.cover_url == _FIRST and gallery.web_url == _PAGE
    assert gallery.tags == ["cosplay"]
    assert gallery.num_favorites is None


async def test_keyword_subscription_does_not_merge_comic_filters(source):
    from types import SimpleNamespace
    from comicfeed.services.subscription import _build_query

    instance, _ = source
    sub = SimpleNamespace(query="Machi馬吉", use_global_search=True)
    assert await _build_query(sub, instance) == "Machi馬吉"


async def test_keyword_subscription_with_unknown_favorites_can_download(
    source, tmp_path, monkeypatch
):
    from comicfeed.infrastructure.database import create_tables, get_session, init_db
    from comicfeed.models import Subscription
    from comicfeed.services.subscription import check_subscription

    instance, _ = source
    monkeypatch.chdir(tmp_path)
    init_db(":memory:")
    await create_tables()
    rules = json.dumps([{"field": "num_favorites", "op": "gte", "value": 1}])
    async with get_session() as session:
        sub = Subscription(name="样本", source_key="4khd", query="Machi馬吉",
                           filter_rules=rules)
        session.add(sub)
        await session.commit()
        galleries, _ = await check_subscription(session, sub.id, instance)
    assert len(galleries) == 1
    result = await download_gallery(instance, galleries[0].native_id, str(tmp_path),
                                    filter_rules=rules, save_to_db=False)
    assert result.page_count == 2


async def test_downloaded_gallery_keeps_unknown_favorites_on_redownload(
    source, tmp_path, monkeypatch
):
    from comicfeed.infrastructure.database import create_tables, init_db
    from comicfeed.web.app import create_app

    instance, _ = source
    app = create_app({"auth_username": "a", "auth_password": "b"})
    monkeypatch.chdir(tmp_path)
    init_db(":memory:")
    await create_tables()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test", auth=("a", "b")) as client:
        for _ in range(2):
            await download_gallery(instance, "42", str(tmp_path))
            response = await client.get("/api/galleries", params={"source_key": "4khd"})
            items = response.json()["items"]
            assert len(items) == 1
            assert items[0]["num_favorites"] is None
            assert items[0]["actual_pages"] == 2


async def test_search_past_last_page_is_empty(source):
    instance, _ = source
    result = await instance.search("样本", page=4)
    assert not result.items and result.current_page == 4


async def test_article_url_and_numeric_urls_resolve_same_id(source):
    instance, requests = source
    assert await instance.resolve_url(_PAGE) == "4khd:42"
    assert instance.parse_url("https://4khd.com/?p=42") == "4khd:42"
    assert instance.parse_url("https://www.4khd.com/wp-json/wp/v2/posts/42") == "4khd:42"
    assert requests[0].headers["referer"] == "https://www.4khd.com/"
    count = len(requests)
    assert await instance.resolve_url("https://4khd.com.invalid/content/12/sample.html") is None
    assert await instance.resolve_url("https://www.4khd.com/search/sample") is None
    assert len(requests) == count
    detail = await instance.get_gallery("42")
    assert detail.native_id == "42" and detail.web_url == _PAGE


def test_all_content_pages_are_extracted_in_order():
    post = deepcopy(_POST)
    post["title"]["rendered"] = "样本[257photos]"
    urls = [f"https://pic.4khd.com/{i:03d}.webp" for i in range(1, 258)]
    post["content"]["rendered"] = "<!--nextpage-->".join(
        f'<img src="{url}">' for url in urls
    )
    detail = FourKHDSource()._parse_gallery_response(post)
    assert detail.page_urls == urls
    assert detail.reported_pages == 257
    assert len(set(detail.page_native_ids)) == 257


@pytest.mark.parametrize("protected", [True, False])
def test_unavailable_or_empty_gallery_fails(protected):
    post = deepcopy(_POST)
    post["content"]["protected"] = protected
    if not protected:
        post["content"]["rendered"] = ""
    with pytest.raises(ValueError, match="未公开|没有公开图片"):
        FourKHDSource()._parse_gallery_response(post)


async def test_incomplete_public_gallery_downloads_and_records_a_success_warning(
    source, tmp_path, monkeypatch
):
    from datetime import datetime
    from comicfeed.infrastructure.database import create_tables, get_session, init_db
    from comicfeed.repositories.download_event import pending_since

    instance, _ = source
    monkeypatch.setitem(_POST["title"], "rendered", "样本[3photos]")
    monkeypatch.chdir(tmp_path)
    init_db(":memory:")
    await create_tables()
    result = await download_gallery(instance, "42", str(tmp_path), cbz_max_pages=1,
                                    subscription_name="Machi馬吉")
    assert result.page_count == 2
    assert len(result.files) == 2
    for path in result.files:
        with ZipFile(path) as archive:
            assert len([name for name in archive.namelist() if name != "ComicInfo.xml"]) == 1
    async with get_session() as session:
        events = await pending_since(session, datetime(1970, 1, 1))
    assert len(events) == 1
    assert events[0].status == "success"
    assert events[0].page_count == 2
    assert events[0].error == ""
    assert events[0].warning == "4KHD 图集图片不完整：标注 3 张，公开 2 张（少 1 张）。"


def test_extra_public_images_are_not_truncated():
    post = deepcopy(_POST)
    post["title"]["rendered"] = "样本[1photos]"
    detail = FourKHDSource()._parse_gallery_response(post)
    assert detail.reported_pages == 2 and detail.page_urls == [_FIRST, _LAST]


async def test_download_uses_requested_range_and_actual_image_bytes(source, media):
    instance, _ = source
    detail = await instance.get_gallery("42")
    callback = []
    pages = await instance.download_pages("42", slice(1, 2), detail=detail,
                                          on_page=lambda: callback.append(1))
    assert pages == [media[_LAST]] and callback == [1]


async def test_html_response_does_not_become_an_image(source):
    instance, _ = source
    detail = await instance.get_gallery("42")
    instance._transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text="<html>Access denied</html>")
    )
    callback = []
    with pytest.raises(ValueError, match="图片响应无效"):
        await instance.download_pages("42", slice(0, 1), detail=detail,
                                      on_page=lambda: callback.append(1))
    assert callback == []


@pytest.mark.parametrize("missing_bytes", [2, 100])
async def test_truncated_jpeg_is_not_a_successful_page(source, media, missing_bytes):
    instance, _ = source
    detail = await instance.get_gallery("42")
    truncated = media[_FIRST][:-missing_bytes]
    downloader = FourKHDSource(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=truncated)
    ))
    callback = []
    with pytest.raises(ValueError, match="图片响应无效"):
        await downloader.download_pages("42", slice(0, 1), detail=detail,
                                        on_page=lambda: callback.append(1))
    assert callback == []


async def test_download_retries_transient_http_failure(source, media, monkeypatch):
    instance, _ = source
    detail = await instance.get_gallery("42")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, content=media[_FIRST])

    instance._transport = httpx.MockTransport(handler)
    monkeypatch.setattr("comicfeed.infrastructure.http_retry.asyncio.sleep", AsyncMock())
    pages = await instance.download_pages("42", slice(0, 1), detail=detail)
    assert len(calls) == 2 and pages == [media[_FIRST]]


@pytest.mark.parametrize("remove_ads,expected_pages", [(False, 2), (True, 1)])
async def test_cbz_keeps_public_tail_page_and_existing_ad_behavior(
    source, media, tmp_path, monkeypatch, remove_ads, expected_pages
):
    instance, _ = source
    instance.remove_ads = remove_ads
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("comicfeed.services.download.record_download_event", AsyncMock())
    result = await download_gallery(instance, "42", str(tmp_path), save_to_db=False)
    assert result.page_count == expected_pages
    with ZipFile(result.files[0]) as archive:
        names = [name for name in archive.namelist() if not name.endswith(".xml")]
        assert len(names) == expected_pages
        assert archive.read("0001.jpg") == media[_FIRST]
        if not remove_ads:
            assert archive.read("0002.webp") == media[_LAST]


async def test_update_check_does_not_request_or_append(source):
    instance, requests = source
    result = await instance.check_updates("42", {"page_ids": ["old"]}, _PAGE)
    assert not result.has_updates and not requests


async def test_connection_checks_json_api(source):
    instance, requests = source
    ok, message = await instance.test_connection()
    assert ok and "API" in message
    assert requests[0].url.path == "/wp-json/wp/v2/posts"
    assert requests[0].url.params["_fields"] == "id"
