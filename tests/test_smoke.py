"""冒烟测试：打真实网站，验证解析器未因网站改版而失效。

运行方式: pytest --run-live -v
凭证自动从项目根目录 comicfeed.db 读取。
"""
import os
import httpx
import pytest

from comicfeed.infrastructure.config import get_source_credentials
from comicfeed.sources.exhentai import ExhentaiSource
from comicfeed.sources.nhentai import NhentaiSource

_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "comicfeed.db")).replace("\\", "/")


async def _init_db():
    from comicfeed.infrastructure.database import init_db
    from comicfeed.infrastructure.config import get_setting, init_crypto
    from comicfeed.infrastructure.tag_translator import get_translator
    init_db(_DB_PATH)
    key = await get_setting("_fernet_key", "")
    if key:
        init_crypto(key)
    await get_translator().load()

async def _check_network(url: str):
    """检查网络连通性。"""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.head(url)
            r.raise_for_status()
    except Exception as e:
        pytest.skip(f"网络不通 {url}: {e}")


# --- exhentai ---

async def _exhentai_source():
    """创建带凭证的 exhentai 源，无凭证则 skip。"""
    if not os.path.exists(_DB_PATH):
        pytest.skip(f"数据库不存在: {_DB_PATH}")
    await _init_db()
    creds = await get_source_credentials("exhentai")
    if not creds:
        pytest.skip("未配置 exhentai Cookie")
    return ExhentaiSource(credentials=creds)


@pytest.mark.live
async def test_exhentai_search_smoke():
    """exhentai 搜索解析 + 翻页游标提取。"""
    s = await _exhentai_source()
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
    gid = 3653399
    gurl = "https://exhentai.org/g/3653399/27fefb4871/"
    s = await _exhentai_source()
    detail = await s.get_gallery(gid, gallery_url=gurl)
    assert detail.title == '[Fanbox] 加瀬大輝 2025.07', "缺少 title"
    assert detail.cover_url == 'https://ehgt.org/w/02/126/11833-na1tg4et.webp', "缺少 cover_url"
    assert len(detail.tags) == 7, "缺少 tags"
    # 此时 translator 没有生效
    assert detail.writers == ['artist：kase daiki'], f"作者解析异常: {detail.writers}"
    assert detail.reported_pages == 40, f"reported_pages 异常: {detail.reported_pages}"
    assert len(detail.page_urls) == 40, "缺少 page_urls"


@pytest.mark.live
async def test_exhentai_nl_extraction_smoke():
    """exhentai 图片页 nl token 提取。"""
    gid = 3653399
    gurl = "https://exhentai.org/g/3653399/27fefb4871/"
    s = await _exhentai_source()
    detail = await s.get_gallery(gid, gallery_url=gurl)
    assert len(detail.page_urls) == 40, "画廊无页面"
    pages = await s.download_pages(gid, slice(0, 1),
                                    gallery_url=gurl, detail=detail)
    assert len(pages) == 1
    assert len(pages[0]) > 0, "图片数据为空"


# --- nhentai ---

async def _nhentai_source():
    creds = await get_source_credentials("nhentai")
    return NhentaiSource(credentials=creds)


@pytest.mark.live
async def test_nhentai_search_smoke():
    """nhentai 搜索 API 响应解析。"""
    s = await _nhentai_source()
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
    s = await _nhentai_source()
    detail = await s.get_gallery(450767)
    assert detail.title == '[鋼鉄しゃぼん玉 (玉ぼん)] 大人になる夏 －おぼえたてHにドハマりする田舎おねショタ－', "缺少 title"
    assert detail.cover_url == 'https://t.nhentai.net/galleries/2523394/cover.jpg', "缺少 cover_url"
    assert len(detail.tags) >= 25, "缺少 tags"
    # 此时 translator 没有生效
    assert detail.writers == ['artist：tamayura banko', 'group：koutetsu shabon dama'], f"作者解析异常: {detail.writers}"
    assert detail.reported_pages == 85, f"reported_pages 异常: {detail.reported_pages}"
    assert len(detail.page_urls) == 85, "缺少 page_urls"
    assert detail.num_favorites > 29000, f"收藏数异常: {detail.num_favorites}"
