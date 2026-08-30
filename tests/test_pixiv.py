"""pixiv 源测试：经 BaseSource 接口接缝，离线 mock 系统边界（HTTP transport / 时钟）。"""

import httpx
import pytest
from httpx import ASGITransport, AsyncClient, MockTransport

from comicfeed.infrastructure.database import create_tables, init_db
from comicfeed.infrastructure.source_manager import SourceManager
from comicfeed.sources.base import AuthSchema

_CLIENT_HASH = "68fa070e55d8ca52b0e989b6b91cc011"  # md5("1234567890" + HASH_SECRET)，独立于实现计算


def _auth_handler(request: httpx.Request) -> httpx.Response:
    """mock app-api：token 刷新 + 排行探活。断言请求头与请求体为外部可观察契约。"""
    if request.url.path == "/auth/token":
        assert request.url.host == "oauth.secure.pixiv.net"
        assert request.headers["X-Client-Time"] == "1234567890"
        assert request.headers["X-Client-Hash"] == _CLIENT_HASH
        assert "refresh_token" in request.content.decode()
        return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600, "refresh_token": "rt-1"})
    if request.url.path == "/v1/illust/ranking":
        assert request.headers["Authorization"] == "Bearer at-1"
        return httpx.Response(200, json={"illusts": []})
    return httpx.Response(404)


def _make_source(handler, **kwargs):
    from comicfeed.sources.pixiv import PixivSource
    defaults = dict(
        credentials={"refresh_token": "rt-0"},
        transport=MockTransport(handler),
        time_fn=lambda: 1234567890.0,
    )
    defaults.update(kwargs)
    return PixivSource(**defaults)


async def test_pixiv_source_validates_as_plugin():
    """pixiv 源满足源插件校验：key/name/version/domains/auth_schema。"""
    from comicfeed.sources.pixiv import PixivSource
    manager = SourceManager()
    assert manager.validate_source(PixivSource) is True
    source = PixivSource()
    assert source.key == "pixiv"
    assert source.name == "Pixiv"
    assert source.version
    assert source.domains == ["app-api.pixiv.net"]
    assert source.auth_schema is AuthSchema.TOKEN


async def test_config_schema_encrypted_refresh_token_with_r18_hint():
    """配置 schema 暴露 refresh_token（加密）与 R-18 账号设置说明。"""
    from comicfeed.sources.pixiv import PixivSource
    schema = PixivSource().get_config_schema()
    by_key = {f["key"]: f for f in schema}
    assert "refresh_token" in by_key
    assert by_key["refresh_token"]["credential"] is True
    assert by_key["refresh_token"]["type"] == "password"
    assert "R-18" in by_key["refresh_token"].get("hint", "")


async def test_valid_refresh_token_connects():
    """有效 refresh_token：刷新成功并探活 app-api。"""
    source = _make_source(_auth_handler)
    ok, message = await source.test_connection()
    assert ok is True
    assert message == "连接成功"


async def test_token_reused_within_expiry():
    """access_token 有效期内复用，不重复请求 token 端点。"""
    auth_calls = 0

    def counting(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls
        if request.url.path == "/auth/token":
            auth_calls += 1
        return _auth_handler(request)

    source = _make_source(counting)
    await source.test_connection()
    await source.test_connection()
    assert auth_calls == 1


async def test_invalid_refresh_token_reports_failure():
    """无效 refresh_token：明确报错而非异常外泄。"""
    def reject(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(400, json={"has_error": True, "errors": {"system": {}}})
        return httpx.Response(404)

    source = _make_source(reject)
    ok, message = await source.test_connection()
    assert ok is False
    assert "refresh_token" in message


# --- Web 端点：/api/sources/{key}/test ---

@pytest.fixture
def app():
    init_db(":memory:")
    return _create_app()


def _create_app():
    from comicfeed.web.app import create_app
    return create_app({"auth_username": "admin", "auth_password": "secret"})


class _OkSource:
    async def test_connection(self):
        return True, "连接成功"


class _OkManager:
    def get_source_cls(self, key):
        return key if key == "pixiv" else None

    def get_source(self, key, credentials=None, proxy=None):
        assert credentials == {"refresh_token": "rt-x"} and proxy is None
        return _OkSource()



# --- 02: 榜单端到端（tracer bullet） ---

_SAMPLE_RANKING = {
    "illusts": [
        {
            "id": 100001, "title": "Sample Art", "type": "illust", "page_count": 1,
            "width": 6000, "height": 4000,
            "user": {"id": 20001, "name": "ArtistA"},
            "image_urls": {
                "medium": "https://i.pximg.net/c/600x1200_90/img-master/img/2024/01/01/00/00/00/100001_p0_master1200.jpg",
                "large": "https://i.pximg.net/c/600x1200_90/img-master/img/2024/01/01/00/00/00/100001_p0_master1200.jpg"},
            "meta_single_page": {"original_image_url": "https://i.pximg.net/img-original/img/2024/01/01/00/00/00/100001_p0.jpg"},
            "meta_pages": [],
            "total_bookmarks": 1234,
            "tags": [{"name": "オリジナル", "translated_name": "原创"}],
            "create_date": "2024-01-01T00:00:00+09:00",
        },
        {
            "id": 100002, "title": "Multi Page", "type": "illust", "page_count": 3,
            "width": 1500, "height": 1200,
            "user": {"id": 20002, "name": "ArtistB"},
            "image_urls": {"medium": "https://i.pximg.net/c/600x1200_90/img-master/img/2024/01/02/00/00/00/100002_p0_master1200.jpg"},
            "meta_single_page": {},
            "meta_pages": [
                {"image_urls": {"large": "https://i.pximg.net/c/600x1200_90/img-master/img/2024/01/02/00/00/00/100002_p0_master1200.jpg",
                                "original": "https://i.pximg.net/img-original/img/2024/01/02/00/00/00/100002_p0.jpg"}},
                {"image_urls": {"large": "https://i.pximg.net/c/600x1200_90/img-master/img/2024/01/02/00/00/00/100002_p1_master1200.jpg",
                                "original": "https://i.pximg.net/img-original/img/2024/01/02/00/00/00/100002_p1.jpg"}},
                {"image_urls": {"large": "https://i.pximg.net/c/600x1200_90/img-master/img/2024/01/02/00/00/00/100002_p2_master1200.jpg",
                                "original": "https://i.pximg.net/img-original/img/2024/01/02/00/00/00/100002_p2.jpg"}},
            ],
            "total_bookmarks": 567,
            "tags": [{"name": "女の子", "translated_name": None}],
            "create_date": "2024-01-02T00:00:00+09:00",
        },
        {
            "id": 100003, "title": "Ugoira Work", "type": "ugoira", "page_count": 1,
            "user": {"id": 20003, "name": "ArtistC"},
            "image_urls": {"medium": "https://i.pximg.net/c/600x1200_90/img-master/img/2024/01/03/00/00/00/100003_p0_master1200.jpg"},
            "meta_single_page": {"original_image_url": "https://i.pximg.net/img-original/img/2024/01/03/00/00/00/100003_p0.jpg"},
            "meta_pages": [],
            "total_bookmarks": 89,
            "tags": [],
            "create_date": "2024-01-03T00:00:00+09:00",
        },
    ],
}


def _ugoira_zip() -> bytes:
    import io
    import zipfile
    from PIL import Image
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i, color in enumerate([(255, 0, 0), (0, 255, 0)]):
            im = Image.new("RGB", (8, 8), color)
            b = io.BytesIO()
            im.save(b, "JPEG")
            zf.writestr(f"00000{i}.jpg", b.getvalue())
    return buf.getvalue()


_UGOIRA_META = {
    "ugoira_metadata": {
        "zip_urls": {"medium": "https://i.pximg.net/img-zip-ugoira/img/2024/01/03/00/00/00/100003_ugoira600x600.zip"},
        "frames": [
            {"file": "000000.jpg", "delay": 100},
            {"file": "000001.jpg", "delay": 150},
        ],
    },
}


def _ranking_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/auth/token":
        return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
    if request.url.path == "/v1/illust/ranking":
        assert request.url.params["mode"] == "day"
        assert request.headers["Authorization"] == "Bearer at-1"
        return httpx.Response(200, json=_SAMPLE_RANKING)
    if request.url.path == "/v1/ugoira/metadata":
        assert request.headers["Authorization"] == "Bearer at-1"
        return httpx.Response(200, json=_UGOIRA_META)
    if request.url.host == "i.pximg.net" and "img-zip-ugoira" in request.url.path:
        assert request.headers.get("Referer") == "https://app-api.pixiv.net"
        return httpx.Response(200, content=_ugoira_zip())
    return httpx.Response(404)


async def test_parse_ranking_url():
    from comicfeed.sources.pixiv import PixivSource
    s = PixivSource()
    assert s.parse_url("https://www.pixiv.net/ranking.php?mode=daily&content=illust") == "pixiv:ranking_daily_illust"
    assert s.parse_url("https://www.pixiv.net/ranking.php?content=ugoira&mode=weekly") == "pixiv:ranking_weekly_ugoira"
    assert s.parse_url("https://www.pixiv.net/ranking.php?mode=daily&content=all") == "pixiv:ranking_daily_all"
    assert s.parse_url("https://www.pixiv.net/ranking.php?mode=daily") is None
    assert s.parse_url("https://www.pixiv.net/artworks/123") is None
    assert s.parse_url("garbage") is None


async def test_ranking_first_check_builds_collection():
    """空 page_ids 的榜单检查：全部静态作品页作为新页返回，动图跳过。"""
    source = _make_source(_ranking_handler)
    result = await source.check_updates(
        "ranking_daily_illust", {"page_ids": []},
        gallery_url="https://www.pixiv.net/ranking.php?mode=daily&content=illust")
    assert result.has_updates is True
    g = result.gallery
    assert g.native_id == "ranking_daily_illust"
    assert g.new_page_ids == ["100001_p0", "100002_p0", "100002_p1", "100002_p2", "100003_webp"]
    assert g.page_count == 5
    assert g.cover_url == "https://i.pximg.net/c/600x1200_90/img-master/img/2024/01/01/00/00/00/100001_p0_master1200.jpg"
    detail = g.detail
    assert detail.page_urls[0] == "https://i.pximg.net/img-original/img/2024/01/01/00/00/00/100001_p0.jpg"
    assert detail.page_urls[3].endswith("100002_p2.jpg")
    assert detail.page_urls[4] == "pixiv-webp:100003"
    assert detail.reported_pages == 5


async def test_ranking_check_skips_known_pages():
    """已收录页 ID 不重复返回；全部已知则无更新。"""
    source = _make_source(_ranking_handler)
    known = {"page_ids": ["100001_p0", "100002_p0", "100002_p1", "100002_p2", "100003_webp"]}
    result = await source.check_updates("ranking_daily_illust", known)
    assert result.has_updates is False


async def test_get_gallery_ranking_refetches():
    """无缓存时 get_gallery 重新取第一页构建详情。"""
    source = _make_source(_ranking_handler)
    detail = await source.get_gallery("ranking_daily_illust")
    assert [u.split("/")[-1] for u in detail.page_urls[:4]] == [
        "100001_p0.jpg", "100002_p0.jpg", "100002_p1.jpg", "100002_p2.jpg"]
    assert detail.page_native_ids == [
        "100001_p0", "100002_p0", "100002_p1", "100002_p2", "100003_webp"]


async def test_download_pages_sends_referer():
    """图片下载携带 Referer 与 iOS App UA，逐页回调。"""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        if request.url.path == "/v1/illust/ranking":
            return httpx.Response(200, json=_SAMPLE_RANKING)
        if request.url.path == "/v1/ugoira/metadata":
            return httpx.Response(200, json=_UGOIRA_META)
        if request.url.host == "i.pximg.net" and "img-zip-ugoira" in request.url.path:
            return httpx.Response(200, content=_ugoira_zip())
        if request.url.host == "i.pximg.net":
            seen.append((request.headers.get("Referer"), request.headers.get("User-Agent", "")))
            return httpx.Response(200, content=b"\xff\xd8\xffpixiv" + request.url.path.encode())
        return httpx.Response(404)

    from comicfeed.infrastructure.database import create_tables, init_db
    init_db(":memory:")
    await create_tables()
    source = _make_source(handler)
    detail = (await source.check_updates("ranking_daily_illust", {"page_ids": []})).gallery.detail
    pages = await source.download_pages("ranking_daily_illust", slice(0, 2), detail=detail)
    assert len(pages) == 2
    assert pages[0].startswith(b"\xff\xd8\xff")
    assert seen and all(ref == "https://app-api.pixiv.net" for ref, _ in seen)
    assert all("PixivIOSApp" in ua for _, ua in seen)



# --- 03: 画师订阅（全量首检 + 增量巡检） ---

def _user_item(wid: int, name: str = "Artist") -> dict:
    return {
        "id": wid, "title": f"Work {wid}", "type": "illust", "page_count": 1,
        "user": {"id": 20000, "name": name},
        "image_urls": {"medium": f"https://i.pximg.net/c/600x1200_90/img-master/img/2024/01/01/00/00/00/{wid}_p0_master1200.jpg"},
        "meta_single_page": {"original_image_url": f"https://i.pximg.net/img-original/img/2024/01/01/00/00/00/{wid}_p0.jpg"},
        "meta_pages": [],
        "total_bookmarks": 100,
        "tags": [],
        "create_date": "2024-01-01T00:00:00+09:00",
    }


def _make_user_handler(pages: dict[int, dict]):
    """pages: {offset: {"illusts": [...], "next": bool}}。记录请求过的 offset。"""
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        if request.url.path == "/v1/user/illusts":
            assert request.headers["Authorization"] == "Bearer at-1"
            offset = int(request.url.params["offset"])
            requested.append(offset)
            page = pages[offset]
            body = {"illusts": page["illusts"], "next_url": f"/v1/user/illusts?offset={offset + 30}" if page.get("next") else None}
            return httpx.Response(200, json=body)
        return httpx.Response(404)

    return handler, requested


async def test_parse_artist_url():
    from comicfeed.sources.pixiv import PixivSource
    s = PixivSource()
    assert s.parse_url("https://www.pixiv.net/users/12345") == "pixiv:12345"
    assert s.parse_url("https://www.pixiv.net/en/users/67890/artworks") == "pixiv:67890"
    assert s.parse_url("https://www.pixiv.net/ranking.php?mode=daily&content=illust") == "pixiv:ranking_daily_illust"


async def test_artist_first_check_paginates_all():
    """空 page_ids 且 max_pages=1（默认）：翻到底，页序按作品 ID 升序。"""
    handler, requested = _make_user_handler({
        0: {"illusts": [_user_item(100012), _user_item(100011), _user_item(100010)], "next": True},
        30: {"illusts": [_user_item(100009), _user_item(100008)], "next": True},
        60: {"illusts": [_user_item(100007)], "next": False},
    })
    source = _make_source(handler)
    result = await source.check_updates("20000", {"page_ids": [], "max_pages": 1})
    assert requested == [0, 30, 60]
    assert result.gallery.new_page_ids == [
        "100007_p0", "100008_p0", "100009_p0", "100010_p0", "100011_p0", "100012_p0"]


async def test_artist_first_check_respects_max_pages_cap():
    """max_pages=2：最多翻 2 页。"""
    handler, requested = _make_user_handler({
        0: {"illusts": [_user_item(100012)], "next": True},
        30: {"illusts": [_user_item(100011)], "next": True},
        60: {"illusts": [_user_item(100010)], "next": False},
    })
    source = _make_source(handler)
    result = await source.check_updates("20000", {"page_ids": [], "max_pages": 2})
    assert requested == [0, 30]
    assert result.gallery.new_page_ids == ["100011_p0", "100012_p0"]


async def test_artist_first_check_zero_max_pages_single_page():
    """max_pages=0：只翻第 1 页。"""
    handler, requested = _make_user_handler({
        0: {"illusts": [_user_item(100012)], "next": True},
        30: {"illusts": [_user_item(100011)], "next": False},
    })
    source = _make_source(handler)
    result = await source.check_updates("20000", {"page_ids": [], "max_pages": 0})
    assert requested == [0]
    assert result.gallery.new_page_ids == ["100012_p0"]


async def test_artist_incremental_check_only_first_page():
    """已有 page_ids：巡检只请求第 1 页，差集出新增作品。"""
    handler, requested = _make_user_handler({
        0: {"illusts": [_user_item(100013), _user_item(100012), _user_item(100011)], "next": True},
        30: {"illusts": [_user_item(100010)], "next": False},
    })
    source = _make_source(handler)
    known = {"page_ids": ["100012_p0", "100011_p0", "100010_p0"], "max_pages": 1}
    result = await source.check_updates("20000", known)
    assert requested == [0]
    assert result.has_updates is True
    assert result.gallery.new_page_ids == ["100013_p0"]


async def test_artist_incremental_check_no_updates():
    """第 1 页无新作品 → 无更新。"""
    handler, requested = _make_user_handler({
        0: {"illusts": [_user_item(100012)], "next": False},
    })
    source = _make_source(handler)
    result = await source.check_updates("20000", {"page_ids": ["100012_p0"], "max_pages": 1})
    assert result.has_updates is False


class _TrackCapture:
    key = "pixiv"
    def parse_url(self, url):
        return "pixiv:20000"
    async def check_updates(self, gallery_id, last_known, gallery_url=""):
        from comicfeed.sources.base import UpdateResult
        return UpdateResult()


async def test_track_gallery_passes_max_pages():
    """服务层把订阅的 search_pages 作为 max_pages 传给源的 check_updates。"""
    from comicfeed.infrastructure.database import create_tables, get_session, init_db
    from comicfeed.models import Subscription
    from comicfeed.services.subscription import track_gallery
    init_db(":memory:")
    await create_tables()

    captured = {}

    class _Capture(_TrackCapture):
        async def check_updates(self, gallery_id, last_known, gallery_url=""):
            captured.update(last_known)
            from comicfeed.sources.base import UpdateResult
            return UpdateResult()

    async with get_session() as session:
        sub = Subscription(name="t", source_key="pixiv", query="https://www.pixiv.net/users/20000",
                           mode="SPECIFIC_GALLERY", search_pages=7)
        session.add(sub)
        await session.commit()
        await track_gallery(session, sub, _Capture())
    assert captured == {"page_ids": [], "max_pages": 7, "filters": ""}



# --- 04: 动图 → 动画 WebP + 跳过记入摘要 ---

async def test_ugoira_download_returns_animated_webp():
    """webp 页经 download_pages 返回合法动画 WebP，delay 生效。"""
    import io
    from PIL import Image
    from comicfeed.infrastructure.database import create_tables, init_db
    init_db(":memory:")
    await create_tables()
    source = _make_source(_ranking_handler)
    detail = (await source.check_updates("ranking_daily_illust", {"page_ids": []})).gallery.detail
    pages = await source.download_pages("ranking_daily_illust", slice(4, 5), detail=detail)
    assert len(pages) == 1
    data = pages[0]
    assert data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    im = Image.open(io.BytesIO(data))
    assert getattr(im, "n_frames", 1) == 2
    # Pillow 的 WebP 插件不暴露帧时长，直接从 ANMF chunk 断言首帧 duration（毫秒，小端）
    idx = data.find(b"ANMF")
    assert idx > 0
    assert int.from_bytes(data[idx + 20:idx + 23], "little") == 100


async def test_ugoira_conversion_failure_skipped_with_note():
    """元数据失败：动图作品跳过、静态作品照常收录、跳过说明可弹出。"""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        if request.url.path == "/v1/illust/ranking":
            return httpx.Response(200, json=_SAMPLE_RANKING)
        if request.url.path == "/v1/ugoira/metadata":
            return httpx.Response(500, json={})
        return httpx.Response(404)

    source = _make_source(handler)
    result = await source.check_updates("ranking_daily_illust", {"page_ids": []})
    assert result.has_updates is True
    assert result.gallery.new_page_ids == ["100001_p0", "100002_p0", "100002_p1", "100002_p2"]
    notes = source.pop_download_notes()
    assert len(notes) == 1
    assert notes[0]["title"] == "Ugoira Work"
    assert "动图转换失败" in notes[0]["error"]
    assert source.pop_download_notes() == []  # 一次性消费


async def test_download_service_records_skip_notes_as_failed_events():
    """下载服务把源的跳过说明记为失败下载事件（进摘要）。"""
    from comicfeed.infrastructure.database import create_tables, get_session, init_db
    from comicfeed.models import DownloadEvent
    from comicfeed.services.download import download_gallery
    from comicfeed.sources.base import AuthSchema, BaseSource, GalleryDetail
    from sqlalchemy import select

    class _NoteSource(BaseSource):
        key = "note-src"
        name = "Note"
        version = "1.0"
        domains = ["note.local"]
        auth_schema = AuthSchema.NONE

        async def search(self, query, page, sort="date"):
            raise NotImplementedError

        async def get_gallery(self, gallery_id, gallery_url=""):
            raise NotImplementedError

        async def download_pages(self, gallery_id, page_range, gallery_url="", detail=None, on_page=None):
            return [b"\xff\xd8\xff" + bytes([i]) for i in range(page_range.start, page_range.stop)]

        async def check_updates(self, gallery_id, last_known, gallery_url=""):
            raise NotImplementedError

        def pop_download_notes(self):
            return [{"title": "Ugoira Work", "error": "动图转换失败: boom"}]

    init_db(":memory:")
    await create_tables()
    detail = GalleryDetail(native_id="x", title="T", cover_url="", web_url="",
                           page_urls=["http://note.local/1.jpg", "http://note.local/2.jpg"],
                           page_native_ids=["a_p0", "b_p0"], reported_pages=2)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        result = await download_gallery(
            source=_NoteSource(), gallery_id="x", output_dir=tmp,
            detail=detail, save_to_db=True, subscription_id=7, subscription_name="订阅A")
    assert len(result.files) == 1
    async with get_session() as session:
        rows = (await session.execute(select(DownloadEvent))).scalars().all()
    by_status = {}
    for r in rows:
        by_status.setdefault(r.status, []).append(r)
    assert len(by_status["success"]) == 1
    assert len(by_status["failed"]) == 1
    f = by_status["failed"][0]
    assert f.title == "Ugoira Work"
    assert f.error == "动图转换失败: boom"
    assert f.subscription_id == 7
    assert f.gallery_id == "note-src:x"



# --- 05: 榜单增量 + 作品级筛选 ---

async def test_work_filter_favorites_applied_per_work():
    """收藏数筛选按作品逐个应用：不达标作品整件排除（含其全部页）。"""
    source = _make_source(_ranking_handler)
    filters = '[{"field": "num_favorites", "op": "gte", "value": 500}]'
    result = await source.check_updates("ranking_daily_illust", {"page_ids": [], "filters": filters})
    assert result.gallery.new_page_ids == ["100001_p0", "100002_p0", "100002_p1", "100002_p2"]


async def test_work_filter_page_count_applied_per_work():
    """页数筛选按作品页数生效。"""
    source = _make_source(_ranking_handler)
    filters = '[{"field": "page_count", "op": "gte", "value": 3}]'
    result = await source.check_updates("ranking_daily_illust", {"page_ids": [], "filters": filters})
    assert result.gallery.new_page_ids == ["100002_p0", "100002_p1", "100002_p2"]


async def test_work_filter_upload_date():
    """上传日期筛选：since_days 足够大全部保留，0 则全部排除（无更新）。"""
    source = _make_source(_ranking_handler)
    result = await source.check_updates("ranking_daily_illust",
                                        {"page_ids": [], "filters": '[{"field": "upload_date", "op": "since_days", "value": 100000}]'})
    assert len(result.gallery.new_page_ids) == 5
    source2 = _make_source(_ranking_handler)
    result2 = await source2.check_updates("ranking_daily_illust",
                                          {"page_ids": [], "filters": '[{"field": "upload_date", "op": "since_days", "value": 0}]'})
    assert result2.has_updates is False


async def test_work_filters_apply_to_artist_collection():
    """画师订阅同样按作品应用筛选。"""
    handler, requested = _make_user_handler({
        0: {"illusts": [
            {**_user_item(100012), "total_bookmarks": 10},
            {**_user_item(100011), "total_bookmarks": 900},
        ], "next": False},
    })
    source = _make_source(handler)
    filters = '[{"field": "num_favorites", "op": "gte", "value": 500}]'
    result = await source.check_updates("20000", {"page_ids": [], "max_pages": 1, "filters": filters})
    assert result.gallery.new_page_ids == ["100011_p0"]


async def test_track_gallery_passes_filters():
    """服务层把订阅的 filter_rules 原样传给源的 check_updates。"""
    from comicfeed.infrastructure.database import create_tables, get_session, init_db
    from comicfeed.models import Subscription
    from comicfeed.services.subscription import track_gallery
    init_db(":memory:")
    await create_tables()

    captured = {}

    class _Capture(_TrackCapture):
        async def check_updates(self, gallery_id, last_known, gallery_url=""):
            captured.update(last_known)
            from comicfeed.sources.base import UpdateResult
            return UpdateResult()

    rules = '[{"field": "num_favorites", "op": "gte", "value": 100}]'
    async with get_session() as session:
        sub = Subscription(name="t", source_key="pixiv", query="https://www.pixiv.net/users/20000",
                           mode="SPECIFIC_GALLERY", search_pages=7, filter_rules=rules)
        session.add(sub)
        await session.commit()
        await track_gallery(session, sub, _Capture())
    assert captured == {"page_ids": [], "max_pages": 7, "filters": rules}



# --- 06: R-18 映射 + 官方中文标签 + 标题元数据 ---

def _mode_handler(expected_mode: str):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        if request.url.path == "/v1/illust/ranking":
            assert request.url.params["mode"] == expected_mode
            assert request.headers["Accept-Language"] == "zh-hans"
            return httpx.Response(200, json={"illusts": []})
        return httpx.Response(404)
    return handler


async def test_r18_ranking_mode_mapping():
    """web 榜单 mode → app mode 映射（含 R-18 系列）。"""
    from comicfeed.sources.pixiv import PixivSource
    s = PixivSource()
    cases = {
        "daily_r18": "day_r18",
        "weekly_r18": "week_r18",
        "male_r18": "day_male_r18",
        "female_r18": "day_female_r18",
        "weekly_r18g": "week_r18g",
        "daily_r18_ai": "day_r18_ai",
        "male": "day_male",
        "rookie": "week_rookie",
    }
    for web_mode, app_mode in cases.items():
        source = _make_source(_mode_handler(app_mode))
        result = await source.check_updates(f"ranking_{web_mode}_illust", {"page_ids": []})
        assert result.has_updates is False  # 空榜单 → 无更新，但请求已按映射发出


async def test_unsupported_ranking_mode_raises():
    """web 有但 app-api 无等价物的榜单模式（如 daily_r18g）明确报错。"""
    import pytest as _pytest
    from comicfeed.sources.pixiv import PixivAuthError
    source = _make_source(_ranking_handler)
    with _pytest.raises(PixivAuthError):
        await source.check_updates("ranking_daily_r18g_illust", {"page_ids": []})


async def test_accept_language_header_on_api_calls():
    """app-api 请求携带 Accept-Language: zh-cn。"""
    seen = []
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        if request.url.path == "/v1/user/illusts":
            seen.append(request.headers.get("Accept-Language"))
            return httpx.Response(200, json={"illusts": [], "next_url": None})
        return httpx.Response(404)
    source = _make_source(handler)
    await source.check_updates("20000", {"page_ids": [], "max_pages": 1})
    assert seen == ["zh-hans"]


async def test_tag_translation_fallback():
    """标签：官方中文优先，缺失回退日文原文。"""
    source = _make_source(_ranking_handler)
    result = await source.check_updates("ranking_daily_illust", {"page_ids": []})
    assert set(result.gallery.detail.tags) == {"原创", "女の子"}


async def test_artist_gallery_title_and_writer():
    """画师 Gallery：title=画师名(画师id)，writer=画师名。"""
    handler, _ = _make_user_handler({
        0: {"illusts": [_user_item(100012, "ArtistName")], "next": False},
    })
    source = _make_source(handler)
    result = await source.check_updates("20000", {"page_ids": [], "max_pages": 1})
    assert result.gallery.title == "ArtistName"
    assert result.gallery.detail.writers == ["ArtistName"]


async def test_ranking_gallery_title_no_writer():
    """榜单 Gallery：title=Pixiv {内容}{周期}榜，writer 为空。"""
    source = _make_source(_ranking_handler)
    result = await source.check_updates("ranking_daily_illust", {"page_ids": []})
    assert result.gallery.title == "Pixiv 插画日榜"
    assert result.gallery.detail.writers == []


async def test_ranking_ugoira_title():
    """动图周榜标题。"""
    source = _make_source(_mode_handler("week"))
    result = await source.check_updates("ranking_weekly_ugoira", {"page_ids": []})
    assert result.has_updates is False


async def test_ranking_all_content_mixed():
    """content=all 综合榜：插画与动图混排收录。"""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        if request.url.path == "/v1/illust/ranking":
            assert request.url.params["mode"] == "day"
            return httpx.Response(200, json=_SAMPLE_RANKING)
        if request.url.path == "/v1/ugoira/metadata":
            return httpx.Response(200, json=_UGOIRA_META)
        if request.url.host == "i.pximg.net" and "img-zip-ugoira" in request.url.path:
            return httpx.Response(200, content=_ugoira_zip())
        return httpx.Response(404)

    source = _make_source(handler)
    result = await source.check_updates("ranking_daily_all", {"page_ids": []})
    assert result.gallery.title == "Pixiv 综合日榜"
    assert result.gallery.new_page_ids == ["100001_p0", "100002_p0", "100002_p1", "100002_p2", "100003_webp"]



# --- 07: 画廊源站链接 + 搜索页透传 ---

def test_web_url_pixiv_mapping():
    """画廊页源站链接：pixiv 各 native_id 形态 → 对应页面。"""
    from comicfeed.web.routes.galleries import _web_url
    assert _web_url("pixiv", "12345") == "https://www.pixiv.net/artworks/12345"
    assert _web_url("pixiv", "ranking_daily_r18_illust") == "https://www.pixiv.net/ranking.php?mode=daily_r18&content=illust"
    assert _web_url("pixiv", "100001") == "https://www.pixiv.net/artworks/100001"
    # 画师画廊优先用已存 web_url（stored_url）
    assert _web_url("pixiv", "2350706", "https://www.pixiv.net/users/2350706") == "https://www.pixiv.net/users/2350706"


def _search_handler(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        if request.url.path == "/v1/search/illust":
            seen.append({"url": str(request.url), "auth": request.headers.get("Authorization")})
            return httpx.Response(200, json={
                "illusts": [_SAMPLE_RANKING["illusts"][0]],
                "next_url": "https://app-api.pixiv.net/v1/search/illust?word=chinese&offset=30",
            })
        return httpx.Response(404)
    return handler


async def test_search_passthrough():
    """搜索透传 app-api：参数映射、结果解析、游标翻页。"""
    from comicfeed.sources.pixiv import PixivSource
    seen = []
    source = _make_source(_search_handler(seen))
    result = await source.search("chinese", page=1)
    assert seen[0]["auth"] == "Bearer at-1"
    assert "word=chinese" in seen[0]["url"]
    assert "sort=date_desc" in seen[0]["url"]
    item = result.items[0]
    assert item.native_id == "100001"
    assert item.page_count == 1
    assert item.num_favorites == 1234
    assert item.web_url == "https://www.pixiv.net/artworks/100001"
    assert item.tags == ["原创"]
    assert source._next_url.endswith("offset=30")
    # 游标翻页：第二次直接请求 next_url
    await source.search("chinese", page=2)
    assert seen[1]["url"].startswith("https://app-api.pixiv.net/v1/search/illust?word=chinese&offset=30")


async def test_sort_options():
    """排序选项不含 premium-only 的人气排序。"""
    from comicfeed.sources.pixiv import PixivSource
    opts = PixivSource().get_sort_options()
    values = [o["value"] for o in opts]
    assert "date_desc" in values and "date_asc" in values
    assert not any("popular" in v for v in values)



# --- 封面代理（pixiv 防盗链） ---

async def test_cover_proxy(app, monkeypatch):
    """/api/cover 仅放行 i.pximg.net，带缓存，且无需认证（img 标签无法带 Basic Auth）。"""
    from comicfeed.web.routes import covers
    calls = []

    async def fake_fetch(url):
        calls.append(url)
        return "image/jpeg", b"\xff\xd8\xffcover"

    monkeypatch.setattr(covers, "_fetch_cover", fake_fetch)
    px_url = "https://i.pximg.net/c/540x540_70/img-master/img/2021/05/01/00/03/33/89501057_p0_master1200.jpg"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/cover", params={"url": px_url})
        assert r.status_code == 200
        assert r.content == b"\xff\xd8\xffcover"
        assert calls == [px_url]
        # 缓存命中
        await client.get("/api/cover", params={"url": px_url})
        assert len(calls) == 1
        # 非 pixiv 主机拒绝
        r2 = await client.get("/api/cover", params={"url": "https://evil.com/x.jpg"})
        assert r2.status_code == 400



# --- 诊断：标签明细日志 ---

async def test_tag_dump_logged_per_work(caplog):
    """每个作品的原始标签对（name=translated_name）记录到日志，供人工核对翻译策略。"""
    with caplog.at_level("DEBUG"):
        source = _make_source(_ranking_handler)
        await source.check_updates("ranking_daily_illust", {"page_ids": []})
    lines = [r.message for r in caplog.records]
    dump1 = next((m for m in lines if m.startswith("pixiv 标签明细") and "work=100001" in m), "")
    dump2 = next((m for m in lines if m.startswith("pixiv 标签明细") and "work=100002" in m), "")
    assert dump1
    assert "オリジナル=原创" in dump1
    assert "女の子=None" in dump2



# --- 标签选译：官方中文含汉字才采用（真实样本来自用户日志） ---

async def test_tag_selection_prefers_cjk_translation():
    """翻译含汉字才采用；罗马音/英文翻译回退日文原文；无翻译回退原文。"""
    from comicfeed.sources.pixiv import PixivSource
    pairs = [
        ({"name": "原神", "translated_name": "Genshin Impact"}, "原神"),
        ({"name": "GenshinImpact", "translated_name": None}, None),  # 无翻译且原文无汉字 → 丢弃
        ({"name": "尻神様", "translated_name": "尻神样"}, "尻神样"),
        ({"name": "九条裟羅", "translated_name": "Kujou Sara"}, "九条裟羅"),
        ({"name": "夜蘭", "translated_name": "Yelan"}, "夜蘭"),
        ({"name": "おっぱい", "translated_name": "欧派"}, "欧派"),
        ({"name": "ふともも", "translated_name": "大腿"}, "大腿"),
        ({"name": "甘雨(原神)", "translated_name": "Ganyu (Genshin Impact)"}, "甘雨(原神)"),
        ({"name": "R-18", "translated_name": "R-18"}, "R-18"),
        ({"name": "Pixiv", "translated_name": "PIXIV"}, "Pixiv"),  # 双方无汉字 → 用原文
        # 里程碑标签（XXXusers入り / 翻译形态 XXX收藏）→ 丢弃
        ({"name": "原神10000users入り", "translated_name": "原神10000收藏"}, None),
        ({"name": "10000users入り", "translated_name": "10000收藏"}, None),
        ({"name": "5000users入り", "translated_name": None}, None),
        ({"name": "收藏", "translated_name": "收藏"}, "收藏"),  # 普通「收藏」标签保留
    ]
    for tag, expected in pairs:
        assert PixivSource._pick_tag(tag) == expected



# --- 节流与限流 ---

def test_throttle_config_parsing():
    """"请求间隔"配置解析：默认 0.1s；0 / - 表示不等待。"""
    from comicfeed.sources.pixiv import PixivSource
    assert PixivSource._throttle_from_cfg({}) == 0.1
    assert PixivSource._throttle_from_cfg({"throttle": "0"}) == 0
    assert PixivSource._throttle_from_cfg({"throttle": "-"}) == 0
    assert PixivSource._throttle_from_cfg({"throttle": "1.5"}) == 1.5
    assert PixivSource._throttle_from_cfg({"throttle": "abc"}) == 0.1


async def test_download_pages_throttles_between_pages(monkeypatch):
    """页间按配置等待（默认 0.1s）。"""
    from comicfeed.infrastructure.database import create_tables, init_db
    init_db(":memory:")
    await create_tables()
    sleeps = []

    async def fake_sleep(d):
        sleeps.append(d)

    async def fake_cfg(key):
        return {}

    monkeypatch.setattr("comicfeed.sources.pixiv.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("comicfeed.infrastructure.config.get_source_config", fake_cfg)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "i.pximg.net" and "img-zip-ugoira" not in request.url.path:
            return httpx.Response(200, content=b"\xff\xd8\xffimg")
        return _ranking_handler(request)

    source = _make_source(handler)
    detail = (await source.check_updates("ranking_daily_illust", {"page_ids": []})).gallery.detail
    pages = await source.download_pages("ranking_daily_illust", slice(0, 2), detail=detail)
    assert len(pages) == 2
    assert any(abs(d - 0.1) < 0.01 for d in sleeps)


async def test_api_pagination_paced(monkeypatch):
    """画师全量翻页：页间 0.5s 间隔。"""
    sleeps = []

    async def fake_sleep(d):
        sleeps.append(d)

    monkeypatch.setattr("comicfeed.sources.pixiv.asyncio.sleep", fake_sleep)
    handler, _ = _make_user_handler({
        0: {"illusts": [_user_item(100012)], "next": True},
        30: {"illusts": [_user_item(100011)], "next": False},
    })
    source = _make_source(handler)
    await source.check_updates("20000", {"page_ids": [], "max_pages": 1})
    assert any(abs(d - 0.5) < 0.01 for d in sleeps)


async def test_429_sets_global_cooldown(monkeypatch):
    """收到 429 → 指数退避重试后失败，并设置全局冷却。"""
    from comicfeed.sources import pixiv as px

    async def no_sleep(d):
        pass

    monkeypatch.setattr("comicfeed.infrastructure.http_retry.asyncio.sleep", no_sleep)
    monkeypatch.setattr("comicfeed.sources.pixiv.asyncio.sleep", no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        if request.url.path == "/v1/user/illusts":
            return httpx.Response(429, headers={"Retry-After": "1"}, json={})
        return httpx.Response(404)

    import pytest as _pytest
    source = _make_source(handler)
    with _pytest.raises(Exception):
        await source.check_updates("20000", {"page_ids": [], "max_pages": 1})
    assert px._cooldown_until > 0



# --- ID 格式：画师纯数字 / 榜单 ranking_mode_content ---

def test_split_ranking_id():
    from comicfeed.sources.pixiv import PixivSource
    assert PixivSource._split_ranking_id("ranking_daily_illust") == ("daily", "illust")
    assert PixivSource._split_ranking_id("ranking_daily_r18_ugoira") == ("daily_r18", "ugoira")
    assert PixivSource._split_ranking_id("ranking_weekly_r18g_manga") == ("weekly_r18g", "manga")
    assert PixivSource._split_ranking_id("ranking_daily_all") == ("daily", "all")


def _make_fake_pixiv_source(pages_map):
    """下载集成测试用假源：按 detail.page_urls 返回可识别 JPEG 头。"""
    from comicfeed.sources.base import AuthSchema, BaseSource

    class _Fake(BaseSource):
        key = "pixiv"
        name = "Pixiv"
        version = "1.0"
        domains = ["fake.local"]
        auth_schema = AuthSchema.NONE

        async def search(self, query, page, sort="date"):
            raise NotImplementedError

        async def get_gallery(self, gallery_id, gallery_url=""):
            raise NotImplementedError

        async def download_pages(self, gallery_id, page_range, gallery_url="", detail=None, on_page=None):
            urls = detail.page_urls[page_range]
            return [b"\xff\xd8\xff" + url.split("/")[-1].encode() for url in urls]

        async def check_updates(self, gallery_id, last_known, gallery_url=""):
            raise NotImplementedError

    return _Fake()


async def test_ranking_cbz_omits_non_numeric_id():
    """榜单 Gallery：CBZ 文件名与 ComicInfo Number 不带 ranking_ id。"""
    import tempfile
    import zipfile
    import xml.etree.ElementTree as ET
    from comicfeed.infrastructure.database import create_tables, init_db
    from comicfeed.services.download import download_gallery
    from comicfeed.sources.base import GalleryDetail
    init_db(":memory:")
    await create_tables()
    detail = GalleryDetail(
        native_id="ranking_daily_illust", title="Pixiv 插画日榜", cover_url="",
        web_url="https://www.pixiv.net/ranking.php?mode=daily&content=illust",
        page_urls=["http://fake.local/100001_p0.jpg", "http://fake.local/100002_p0.jpg"],
        page_native_ids=["100001_p0", "100002_p0"], reported_pages=2, display_id="")
    with tempfile.TemporaryDirectory() as tmp:
        result = await download_gallery(source=_make_fake_pixiv_source({}), gallery_id="ranking_daily_illust",
                                        output_dir=tmp, detail=detail, save_to_db=True)
        assert len(result.files) == 1
        assert result.files[0].endswith("Pixiv 插画日榜.cbz")
        with zipfile.ZipFile(result.files[0]) as z:
            root = ET.fromstring(z.read("ComicInfo.xml"))
            num = root.find("Number")
            assert num is None or not (num.text or "").strip()


async def test_ranking_incremental_appends_by_title():
    """榜单增量：文件名无 [id] 时按标题匹配旧卷追加，不产生重复卷。"""
    import tempfile
    from comicfeed.infrastructure.database import create_tables, init_db
    from comicfeed.io.cbz import read_cbz_pages
    from comicfeed.services.download import download_gallery
    from comicfeed.sources.base import GalleryDetail
    init_db(":memory:")
    await create_tables()
    base = dict(native_id="ranking_daily_illust", title="Pixiv 插画日榜", cover_url="",
                web_url="https://www.pixiv.net/ranking.php?mode=daily&content=illust", display_id="")
    first = GalleryDetail(page_urls=["http://fake.local/a.jpg", "http://fake.local/b.jpg"],
                          page_native_ids=["100001_p0", "100002_p0"], reported_pages=2, **base)
    second = GalleryDetail(page_urls=["http://fake.local/c.jpg"],
                           page_native_ids=["100003_p0"], reported_pages=1, **base)
    with tempfile.TemporaryDirectory() as tmp:
        r1 = await download_gallery(source=_make_fake_pixiv_source({}), gallery_id="ranking_daily_illust",
                                    output_dir=tmp, detail=first, save_to_db=True)
        r2 = await download_gallery(source=_make_fake_pixiv_source({}), gallery_id="ranking_daily_illust",
                                    output_dir=tmp, detail=second, save_to_db=True, append_pages=True)
        assert len(r1.files) == 1 and len(r2.files) == 1
        assert r2.files[0].endswith("Pixiv 插画日榜.cbz")
        pages = read_cbz_pages(r2.files[0])
        assert len(pages) == 3



# --- 保留原始页面文件名 ---

def test_pack_cbz_keeps_original_page_names():
    """keep_page_names=True：条目名含 artwork id，页码三位补零保证字典序=数字序。"""
    import io
    import zipfile
    from comicfeed.io.cbz import pack_cbz
    from comicfeed.sources.base import GalleryDetail
    # 12 页作品：不补零时 p10 会排在 p2 前
    ids = [f"149035907_p{i}" for i in range(1, 13)]
    detail = GalleryDetail(
        native_id="2350706", title="T", cover_url="", web_url="",
        page_urls=["http://x/x.jpg"] * 12,
        page_native_ids=ids,
        reported_pages=12, keep_page_names=True)
    buf = io.BytesIO()
    pack_cbz(buf, "t.cbz", detail, [b"\xff\xd8\xffa"] * 12)
    buf.seek(0)
    with zipfile.ZipFile(buf) as z:
        names = [n for n in z.namelist() if not n.endswith(".xml")]
    assert names[0] == "149035907_p001.jpg"
    assert names[-1] == "149035907_p012.jpg"
    # 阅读器按名字典序：补零后排序即页码顺序
    assert sorted(names) == names


async def test_pixiv_detail_carries_keep_page_names():
    """pixiv 的 detail 声明保留原始页面文件名。"""
    source = _make_source(_ranking_handler)
    result = await source.check_updates("ranking_daily_illust", {"page_ids": []})
    assert result.gallery.detail.keep_page_names is True



# --- 分卷页名回归 ---

async def test_split_volumes_use_correct_page_names():
    """分卷下载：第 2 卷条目名对应正确的作品页 id，不复读第 1 卷。"""
    import tempfile
    import zipfile
    from comicfeed.infrastructure.database import create_tables, init_db
    from comicfeed.services.download import download_gallery
    from comicfeed.sources.base import GalleryDetail
    init_db(":memory:")
    await create_tables()
    detail = GalleryDetail(
        native_id="2350706", title="画师名", cover_url="", web_url="",
        page_urls=[f"http://fake.local/{i}.jpg" for i in range(30)],
        page_native_ids=[f"149035907_p{i}" for i in range(30)],
        reported_pages=30, keep_page_names=True)
    with tempfile.TemporaryDirectory() as tmp:
        result = await download_gallery(source=_make_fake_pixiv_source({}), gallery_id="2350706",
                                        output_dir=tmp, detail=detail, save_to_db=True,
                                        cbz_max_pages=20)
        assert len(result.files) == 2
        with zipfile.ZipFile(result.files[1]) as z:
            names = [n for n in z.namelist() if not n.endswith(".xml")]
    # 第 2 卷 = 绝对页 21..30 = p020..p029；修复前会复读 p000..p009
    assert names[0] == "149035907_p020.jpg"
    assert names[-1] == "149035907_p029.jpg"


async def test_incremental_append_names_only_new_pages():
    """增量追加：旧页保持无名（序号），新页用其作品页 id。"""
    import tempfile
    from comicfeed.infrastructure.database import create_tables, init_db
    from comicfeed.io.cbz import read_cbz_pages
    from comicfeed.services.download import download_gallery
    from comicfeed.sources.base import GalleryDetail
    init_db(":memory:")
    await create_tables()
    base = dict(native_id="2350706", title="画师名", cover_url="", web_url="", keep_page_names=True)
    first = GalleryDetail(page_urls=["http://fake.local/a.jpg", "http://fake.local/b.jpg"],
                          page_native_ids=["149035907_p0", "149035907_p1"],
                          reported_pages=2, **base)
    second = GalleryDetail(page_urls=["http://fake.local/c.jpg"],
                           page_native_ids=["149035907_p2"],
                           reported_pages=1, **base)
    with tempfile.TemporaryDirectory() as tmp:
        await download_gallery(source=_make_fake_pixiv_source({}), gallery_id="2350706",
                               output_dir=tmp, detail=first, save_to_db=True)
        r2 = await download_gallery(source=_make_fake_pixiv_source({}), gallery_id="2350706",
                                    output_dir=tmp, detail=second, save_to_db=True, append_pages=True)
        import zipfile as _zipfile
        with _zipfile.ZipFile(r2.files[0]) as z:
            names = [n for n in z.namelist() if not n.endswith(".xml")]
        assert len(read_cbz_pages(r2.files[0])) == 3
    assert names == ["0001.jpg", "0002.jpg", "149035907_p002.jpg"]




# --- 图片大小上限：程序内压缩 ---

def _noise_jpeg(size: int = 1200, quality: int = 95) -> bytes:
    import io
    import random
    from PIL import Image
    random.seed(42)
    im = Image.new("RGB", (size, size))
    px = im.load()
    for y in range(0, size, 4):
        for x in range(0, size, 4):
            c = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
            for dy in range(4):
                for dx in range(4):
                    px[x + dx, y + dy] = c
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def test_max_bytes_config_parsing():
    """"图片大小上限"配置：0/留空/非法 = 不压缩；否则换算为字节。"""
    from comicfeed.sources.pixiv import PixivSource
    assert PixivSource._max_bytes_from_cfg({}) == 0
    assert PixivSource._max_bytes_from_cfg({"max_mb": "0"}) == 0
    assert PixivSource._max_bytes_from_cfg({"max_mb": "abc"}) == 0
    assert PixivSource._max_bytes_from_cfg({"max_mb": "1"}) == 1048576


def test_compress_image_small_and_invalid_untouched():
    """未超限/无法解码的字节原样返回。"""
    from comicfeed.sources.pixiv import PixivSource
    small = _noise_jpeg(200, 80)
    assert PixivSource._compress_image(small, 10_000_000) == small
    assert PixivSource._compress_image(b"\x00\x01not-an-image", 100) == b"\x00\x01not-an-image"


def test_compress_image_jpeg_shrinks():
    """超限 JPEG：重编码后显著变小且仍为合法 JPEG；像素按比例缩小（长边≥1200）。"""
    import io
    from PIL import Image
    from comicfeed.sources.pixiv import PixivSource
    big = _noise_jpeg(2400, 95)
    out = PixivSource._compress_image(big, 200_000)
    assert len(out) < len(big) * 0.5
    assert out.startswith(b"\xff\xd8\xff")
    with Image.open(io.BytesIO(out)) as im:
        w, h = im.size
    assert max(w, h) < 2400 and max(w, h) >= 1200


def test_compress_image_proportional_aspect():
    """非方图等比缩小：宽高比保持不变。"""
    import io
    from PIL import Image
    from comicfeed.sources.pixiv import PixivSource
    big = _noise_jpeg(1600, 95)
    # 裁成 1600x800（2:1）
    im = Image.open(io.BytesIO(big)).crop((0, 0, 1600, 800))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    out = PixivSource._compress_image(buf.getvalue(), 50_000)
    with Image.open(io.BytesIO(out)) as res:
        w, h = res.size
    assert w == h * 2
    assert w < 1600


def test_compress_image_rgba_png_untouched_rgb_png_to_jpeg():
    """RGBA PNG（透明）不动；RGB PNG 转 JPEG 变小。"""
    import io
    from PIL import Image
    from comicfeed.sources.pixiv import PixivSource
    rgba = io.BytesIO()
    Image.new("RGBA", (800, 800), (255, 0, 0, 128)).save(rgba, "PNG")
    assert PixivSource._compress_image(rgba.getvalue(), 1000) == rgba.getvalue()
    rgb = io.BytesIO()
    Image.new("RGB", (800, 800), (0, 128, 255)).save(rgb, "PNG")
    out = PixivSource._compress_image(rgb.getvalue(), 1000)
    assert out.startswith(b"\xff\xd8\xff")


async def test_download_pages_compresses_oversize_pages(monkeypatch):
    """下载时超限页压缩、小页与动图页原样。"""
    from comicfeed.infrastructure.database import create_tables, init_db
    init_db(":memory:")
    await create_tables()
    big = _noise_jpeg(1200, 95)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        if request.url.path == "/v1/illust/ranking":
            return httpx.Response(200, json=_SAMPLE_RANKING)
        if request.url.path == "/v1/ugoira/metadata":
            return httpx.Response(200, json=_UGOIRA_META)
        if request.url.host == "i.pximg.net" and "img-zip-ugoira" in request.url.path:
            return httpx.Response(200, content=_ugoira_zip())
        if request.url.host == "i.pximg.net":
            if "100001" in request.url.path:
                return httpx.Response(200, content=big)
            return httpx.Response(200, content=b"\xff\xd8\xffsmall")

    async def fake_cfg(key):
        return {"max_mb": "0.2"}

    monkeypatch.setattr("comicfeed.infrastructure.config.get_source_config", fake_cfg)
    source = _make_source(handler)
    detail = (await source.check_updates("ranking_daily_illust", {"page_ids": []})).gallery.detail
    pages = await source.download_pages("ranking_daily_illust", slice(0, 5), detail=detail)
    # 第 1 页（大图）被压缩变小且合法；小图原样；webp 页（索引 4）不受影响
    assert len(pages[0]) < len(big)
    assert pages[0].startswith(b"\xff\xd8\xff")
    assert pages[1] == b"\xff\xd8\xffsmall"
    assert pages[3] == b"\xff\xd8\xffsmall"
    assert pages[4].startswith(b"RIFF") and pages[4][8:12] == b"WEBP"


async def test_test_connection_endpoint(app, monkeypatch):
    """测试连接端点返回源的探活结果；未知源 404。"""
    await create_tables()
    monkeypatch.setattr("comicfeed.web.routes.sources._get_manager", lambda: _OkManager())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/sources/pixiv/test", auth=("admin", "secret"),
                                 json={"credentials": {"refresh_token": "rt-x"}})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "message": "连接成功"}
        resp2 = await client.post("/api/sources/nope/test", auth=("admin", "secret"))
        assert resp2.status_code == 404
