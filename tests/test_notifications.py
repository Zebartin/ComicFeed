import json

from comicfeed.hooks import Event
from comicfeed.notifications import build_payload, send_webhook


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
