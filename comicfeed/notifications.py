import httpx

from comicfeed.hooks import Event


def build_payload(event: Event) -> dict:
    """构建 webhook JSON 负载。"""
    payload = {"event": event.name}
    # 过滤掉太长的列表数据（如 files 列表）
    for k, v in event.data.items():
        if isinstance(v, list) and len(v) > 5:
            payload[k] = v[:5]
            payload[f"{k}_count"] = len(v)
        else:
            payload[k] = v
    return payload


async def send_webhook(url: str, event: Event, _client=None):
    """发送 webhook POST 请求。"""
    payload = build_payload(event)
    if _client is not None:
        async with _client as client:
            await client.post(url, json=payload)
    else:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json=payload)
