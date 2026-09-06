import json
from unittest.mock import MagicMock, patch

from comicfeed.infrastructure.notifications import build_payload, send_email, send_webhook


def test_build_payload():
    """构建 webhook 消息负载。"""
    event = {"name": "gallery.created", "data": {
        "gallery_id": "nhentai:123",
        "title": "Test Comic",
        "files": ["file1.cbz", "file2.cbz"],
    }}
    payload = build_payload(event)
    assert payload["event"] == "gallery.created"
    assert payload["gallery_id"] == "nhentai:123"
    assert payload["title"] == "Test Comic"
    assert "files" in payload


async def test_send_webhook_with_mock_client():
    """send_webhook 发送正确的 POST 请求。"""
    captured_url = []
    captured_data = []

    class FakeResponse:
        status_code = 200

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            pass
        async def post(self, url, json=None, **_):
            captured_url.append(url)
            captured_data.append(json)
            return FakeResponse()

    event = {"name": "gallery.created", "data": {"gallery_id": "nh:1"}}
    client = FakeClient()
    await send_webhook("https://hook.example.com", event, _client=client)

    assert captured_url == ["https://hook.example.com"]
    assert captured_data[0]["event"] == "gallery.created"


async def test_send_email_starttls():
    """send_email 发送 SMTP 邮件 (port 587 STARTTLS)。"""
    event = {"name": "gallery.created", "data": {
        "gallery_id": "nhentai:123", "title": "Test Comic", "files": ["a.cbz"],
    }}
    config = {"host": "smtp.example.com", "port": 587, "user": "u", "password": "p", "to": "me@x.com"}

    with patch("smtplib.SMTP") as mock:
        mock.return_value.__enter__.return_value = mock.return_value
        await send_email(config, event)
        mock.assert_called_once_with("smtp.example.com", 587)
        mock.return_value.starttls.assert_called_once()
        mock.return_value.login.assert_called_once_with("u", "p")


# --- 邮件封面：内嵌 / 公网代理 / 降级 ---

async def _async_bytes(data: bytes):
    return data


async def test_cover_public_mode_uses_proxy_url(monkeypatch):
    """"公网域名"配置时：img 指向自家 /api/cover，不抓取、无附件。"""
    from comicfeed.infrastructure import notifications as nt
    called = []

    async def boom(url):
        called.append(url)
        raise AssertionError("公网模式不应抓图")

    monkeypatch.setattr(nt, "_fetch_cover_bytes", boom)
    atts = []
    tag = await nt._make_cover("https://i.pximg.net/x/1.jpg", "https://comics.example.com", atts, "c1")
    assert "https://comics.example.com/api/cover?url=" in tag
    assert "cid:" not in tag
    assert atts == [] and called == []


async def test_cover_embed_success(monkeypatch):
    """内嵌模式：抓取成功 → CID 附件 + cid: 引用。"""
    from comicfeed.infrastructure import notifications as nt
    monkeypatch.setattr(nt, "_fetch_cover_bytes",
                        lambda url: _async_bytes(b"\x89PNG\r\n\x1a\n0011"))
    atts = []
    tag = await nt._make_cover("https://i.pximg.net/x/1.png", "", atts, "c1")
    assert tag.startswith("<img src='cid:c1'")
    assert len(atts) == 1
    assert "<c1>" in str(atts[0]["Content-ID"])


async def test_cover_embed_failure_falls_back(monkeypatch):
    """抓取失败 → 回退远程 URL，无附件。"""
    from comicfeed.infrastructure import notifications as nt
    async def fail(url):
        raise httpx.ConnectError("no network")
    monkeypatch.setattr(nt, "_fetch_cover_bytes", fail)
    atts = []
    tag = await nt._make_cover("https://i.pximg.net/x/1.jpg", "", atts, "c1")
    assert "https://i.pximg.net/x/1.jpg" in tag and "cid:" not in tag
    assert atts == []


async def test_cover_embed_oversize_falls_back(monkeypatch):
    """超过 300KB → 回退远程 URL。"""
    from comicfeed.infrastructure import notifications as nt
    big = b"x" * (nt._COVER_MAX_BYTES + 1)
    monkeypatch.setattr(nt, "_fetch_cover_bytes", lambda url: _async_bytes(big))
    atts = []
    tag = await nt._make_cover("https://i.pximg.net/x/1.jpg", "", atts, "c1")
    assert "https://i.pximg.net/x/1.jpg" in tag and atts == []


async def test_send_email_ssl():
    """send_email 发送 SMTP 邮件 (port 465 SSL)。"""
    event = {"name": "gallery.created", "data": {"gallery_id": "x", "title": "t", "files": []}}
    config = {"host": "smtp.example.com", "port": 465, "user": "u", "password": "p", "to": "me@x.com"}

    with patch("smtplib.SMTP_SSL") as mock:
        mock.return_value.__enter__.return_value = mock.return_value
        await send_email(config, event)
        mock.assert_called_once()
        mock.return_value.login.assert_called_once_with("u", "p")
