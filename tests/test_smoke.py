"""冒烟测试：打真实网站，验证解析器未因网站改版而失效。

运行方式: pytest --run-live
凭证自动从 comicfeed.db 读取，无需额外配置。
"""
import httpx
import pytest

from comicfeed.infrastructure.config import get_source_credentials
from comicfeed.sources.exhentai import ExhentaiSource
from comicfeed.sources.nhentai import NhentaiSource


async def _check_network(url: str):
    """检查网络连通性。"""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.head(url)
            r.raise_for_status()
    except Exception as e:
        pytest.skip(f"网络不通 {url}: {e}")


# --- exhentai ---

def _exhentai_source():
    """创建带凭证的 exhentai 源，无凭证则 skip。"""
    import asyncio
    creds = asyncio.run(get_source_credentials("exhentai"))
    if not creds:
        pytest.skip("未配置 exhentai Cookie")
    return ExhentaiSource(credentials=creds)


@pytest.mark.live
async def test_exhentai_search_smoke():
    """exhentai 搜索解析 + 翻页游标提取。"""
    await _check_network("https://exhentai.org")
    s = _exhentai_source()
    result = await s.search("chinese", page=0)
    assert result.items, "搜索结果为空"
    g = result.items[0]
    assert g.native_id, "缺少 native_id"
    assert g.title, "缺少 title"
    assert g.cover_url, "缺少 cover_url"
    assert isinstance(g.page_count, int) and g.page_count > 0, f"page_count 异常: {g.page_count}"
    assert result.next_url, "缺少翻页游标 next_url"


@pytest.mark.live
async def test_exhentai_gallery_detail_smoke():
    """exhentai 画廊详情解析。"""
    await _check_network("https://exhentai.org")
    s = _exhentai_source()
    result = await s.search("chinese", page=0)
    assert result.items, "搜索无结果"
    gid = result.items[0].native_id
    detail = await s.get_gallery(gid, gallery_url=result.items[0].web_url)
    assert detail.title, "缺少 title"
    assert detail.cover_url, "缺少 cover_url"
    assert detail.tags, "缺少 tags"
    assert detail.reported_pages > 0, f"reported_pages 异常: {detail.reported_pages}"
    assert detail.page_urls, "缺少 page_urls"


@pytest.mark.live
async def test_exhentai_nl_extraction_smoke():
    """exhentai 图片页 nl token 提取。"""
    await _check_network("https://exhentai.org")
    s = _exhentai_source()
    result = await s.search("chinese", page=0)
    assert result.items, "搜索无结果"
    gid = result.items[0].native_id
    detail = await s.get_gallery(gid, gallery_url=result.items[0].web_url)
    assert detail.page_urls, "画廊无页面"
    pages = await s.download_pages(gid, slice(0, 1),
                                    gallery_url=result.items[0].web_url, detail=detail)
    assert len(pages) == 1
    assert len(pages[0]) > 0, "图片数据为空"


# --- nhentai ---

def _nhentai_source():
    import asyncio
    creds = asyncio.run(get_source_credentials("nhentai"))
    return NhentaiSource(credentials=creds)


@pytest.mark.live
async def test_nhentai_search_smoke():
    """nhentai 搜索 API 响应解析。"""
    await _check_network("https://nhentai.net")
    s = _nhentai_source()
    result = await s.search("chinese", page=1)
    assert result.items, "搜索结果为空"
    g = result.items[0]
    assert g.native_id, "缺少 native_id"
    assert g.title, "缺少 title"
    assert g.cover_url, "缺少 cover_url"
    assert isinstance(g.page_count, int) and g.page_count > 0, f"page_count 异常: {g.page_count}"


@pytest.mark.live
async def test_nhentai_gallery_detail_smoke():
    """nhentai 画廊详情 API 响应解析。"""
    await _check_network("https://nhentai.net")
    s = _nhentai_source()
    result = await s.search("chinese", page=1)
    assert result.items, "搜索无结果"
    gid = result.items[0].native_id
    detail = await s.get_gallery(gid)
    assert detail.title, "缺少 title"
    assert detail.cover_url, "缺少 cover_url"
    assert detail.tags, "缺少 tags"
    assert detail.reported_pages > 0, f"reported_pages 异常: {detail.reported_pages}"
    assert detail.page_urls, "缺少 page_urls"
