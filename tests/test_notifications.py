import json
from unittest.mock import MagicMock, patch

from comicfeed.hooks import Event
from comicfeed.notifications import build_payload, send_email, send_webhook


def test_build_payload():
    """构建 webhook 消息负载。"""
    event = Event("gallery.created", {
        "gallery_id": "nhentai:123",
        "title": "Test Comic",
        "files": ["file1.cbz", "file2.cbz"],
    })
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

    event = Event("gallery.created", {"gallery_id": "nh:1"})
    client = FakeClient()
    await send_webhook("https://hook.example.com", event, _client=client)

    assert captured_url == ["https://hook.example.com"]
    assert captured_data[0]["event"] == "gallery.created"


async def test_send_email_starttls():
    """send_email 发送 SMTP 邮件 (port 587 STARTTLS)。"""
    event = Event("gallery.created", {
        "gallery_id": "nhentai:123", "title": "Test Comic", "files": ["a.cbz"],
    })
    config = {"host": "smtp.example.com", "port": 587, "user": "u", "password": "p", "to": "me@x.com"}

    with patch("smtplib.SMTP") as mock:
        mock.return_value.__enter__.return_value = mock.return_value
        await send_email(config, event)
        mock.assert_called_once_with("smtp.example.com", 587)
        mock.return_value.starttls.assert_called_once()
        mock.return_value.login.assert_called_once_with("u", "p")


async def test_send_email_ssl():
    """send_email 发送 SMTP 邮件 (port 465 SSL)。"""
    event = Event("gallery.created", {"gallery_id": "x", "title": "t", "files": []})
    config = {"host": "smtp.example.com", "port": 465, "user": "u", "password": "p", "to": "me@x.com"}

    with patch("smtplib.SMTP_SSL") as mock:
        mock.return_value.__enter__.return_value = mock.return_value
        await send_email(config, event)
        mock.assert_called_once()
        mock.return_value.login.assert_called_once_with("u", "p")
