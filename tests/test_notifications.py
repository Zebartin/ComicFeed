import json
import re
from unittest.mock import MagicMock, patch

import httpx

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


async def test_cover_embed_failure_falls_back(monkeypatch, caplog):
    """抓取失败 → 回退远程 URL，无附件，记 warning（含 URL 与原因）。"""
    from comicfeed.infrastructure import notifications as nt
    async def fail(url):
        raise httpx.ConnectError("no network")
    monkeypatch.setattr(nt, "_fetch_cover_bytes", fail)
    atts = []
    with caplog.at_level("WARNING"):
        tag = await nt._make_cover("https://i.pximg.net/x/1.jpg", "", atts, "c1")
    assert "https://i.pximg.net/x/1.jpg" in tag and "cid:" not in tag
    assert atts == []
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("https://i.pximg.net/x/1.jpg" in m and "no network" in m for m in warnings)


async def test_cover_embed_oversize_falls_back(monkeypatch, caplog):
    """超过 300KB → 回退远程 URL，记 warning。"""
    from comicfeed.infrastructure import notifications as nt
    big = b"x" * (nt._COVER_MAX_BYTES + 1)
    monkeypatch.setattr(nt, "_fetch_cover_bytes", lambda url: _async_bytes(big))
    atts = []
    with caplog.at_level("WARNING"):
        tag = await nt._make_cover("https://i.pximg.net/x/1.jpg", "", atts, "c1")
    assert "https://i.pximg.net/x/1.jpg" in tag and atts == []
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("https://i.pximg.net/x/1.jpg" in m for m in warnings)



async def test_cover_public_mode_normalizes_domain():
    """"公网域名"缺协议/带尾斜杠时自动归一化。"""
    from comicfeed.infrastructure import notifications as nt
    atts = []
    tag = await nt._make_cover("https://i.pximg.net/x/1.jpg", "comics.example.com", atts, "c1")
    assert tag.startswith("<img src='https://comics.example.com/api/cover?url=")
    tag2 = await nt._make_cover("https://i.pximg.net/x/1.jpg", "https://comics.example.com/", atts, "c2")
    assert tag2.startswith("<img src='https://comics.example.com/api/cover?url=")


def _capture_embed_send(monkeypatch) -> list:
    """内嵌模式 + 假抓图（图片内容 = PNG 头 + URL）+ 截获待发邮件。"""
    from comicfeed.infrastructure import config as cfg
    from comicfeed.infrastructure import notifications as nt

    async def no_domain(key, default=None):
        return ""

    monkeypatch.setattr(cfg, "get_setting", no_domain)
    monkeypatch.setattr(nt, "_fetch_cover_bytes",
                        lambda url: _async_bytes(b"\x89PNG\r\n\x1a\n" + url.encode()))
    sent = []
    monkeypatch.setattr(nt, "_smtp_send", lambda config, msg: sent.append(msg))
    return sent


async def test_digest_embed_cids_unique_across_subscriptions(monkeypatch):
    """摘要多订阅：内嵌封面 CID 在整封邮件内唯一，每个 img 引用各自的封面。"""
    from datetime import datetime
    from comicfeed.infrastructure import notifications as nt
    sent = _capture_embed_send(monkeypatch)

    def sub(name, *covers):
        return {"name": name, "count": len(covers), "failed_count": 0, "failed": [],
                "items": [{"cover_url": c, "title": c, "gallery_id": f"x:{c}"} for c in covers]}

    digest = {"since": datetime(2026, 9, 1), "until": datetime(2026, 9, 2),
              "total_count": 3, "total_failed": 0,
              "subscriptions": [sub("A", "https://a/1.jpg", "https://a/2.jpg"), sub("B", "https://b/1.jpg")]}
    await nt.send_digest_email({"user": "u", "to": "t"}, digest)

    msg = sent[0]
    html = next(p for p in msg.walk() if p.get_content_type() == "text/html").get_payload(decode=True).decode()
    cids = re.findall(r"src='cid:([^']+)'", html)
    assert len(cids) == 3 and len(set(cids)) == 3
    images = {p["Content-ID"].strip("<>"): p.get_payload(decode=True)
              for p in msg.walk() if p.get_content_maintype() == "image"}
    assert [images[c][8:] for c in cids] == [b"https://a/1.jpg", b"https://a/2.jpg", b"https://b/1.jpg"]


async def test_html_email_is_multipart_related(monkeypatch):
    """HTML 邮件（单发/摘要）为 multipart/related：正文居首，内嵌封面与之同组以供 cid: 解析。"""
    from datetime import datetime
    from comicfeed.infrastructure import notifications as nt
    sent = _capture_embed_send(monkeypatch)
    item = {"cover_url": "https://a/1.jpg", "title": "t", "gallery_id": "x:1"}
    await nt.send_email({"user": "u", "to": "t"},
                        {"name": "test", "data": {"count": 1, "subscription": "A", "galleries": [item]}})
    await nt.send_digest_email({"user": "u", "to": "t"}, {
        "since": datetime(2026, 9, 1), "until": datetime(2026, 9, 2), "total_count": 1, "total_failed": 0,
        "subscriptions": [{"name": "A", "count": 1, "failed_count": 0, "failed": [], "items": [item]}]})
    assert len(sent) == 2
    for msg in sent:
        assert msg.get_content_type() == "multipart/related"
        assert [p.get_content_type() for p in msg.get_payload()] == ["text/html", "image/png"]


async def test_send_email_ssl():
    """send_email 发送 SMTP 邮件 (port 465 SSL)。"""
    event = {"name": "gallery.created", "data": {"gallery_id": "x", "title": "t", "files": []}}
    config = {"host": "smtp.example.com", "port": 465, "user": "u", "password": "p", "to": "me@x.com"}

    with patch("smtplib.SMTP_SSL") as mock:
        mock.return_value.__enter__.return_value = mock.return_value
        await send_email(config, event)
        mock.assert_called_once()
        mock.return_value.login.assert_called_once_with("u", "p")
