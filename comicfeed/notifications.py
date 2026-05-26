import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from comicfeed.hooks import Event


def build_payload(event: Event) -> dict:
    """构建 webhook JSON 负载。"""
    payload = {"event": event.name}
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


async def send_email(config: dict, event: Event):
    """发送邮件通知。config 包含 host/port/user/password/to。"""
    subject = f"[ComicFeed] {event.name}"
    title = event.data.get("title", "")
    body = f"事件: {event.name}\n标题: {title}\n"
    for k, v in event.data.items():
        if k in ("title", "files"):
            continue
        body += f"{k}: {v}\n"
    if "files" in event.data:
        body += f"文件: {', '.join(event.data['files'][:5])}\n"

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = config.get("user", "")
    msg["To"] = config.get("to", "")
    msg.attach(MIMEText(body, "plain", "utf-8"))

    def _send():
        port = config["port"]
        if port == 465:
            import ssl
            ctx = ssl.create_default_context()
            s = smtplib.SMTP_SSL(config["host"], port, context=ctx)
        else:
            s = smtplib.SMTP(config["host"], port)
        with s:
            if port != 465:
                s.starttls()
            s.login(config["user"], config["password"])
            s.send_message(msg)

    await asyncio.to_thread(_send)


async def _on_event_send_email(event: Event):
    """事件钩子：发送邮件通知。"""
    from comicfeed.config import get_setting
    host = await get_setting("smtp_host", "")
    if not host:
        return
    config = {
        "host": host,
        "port": int(await get_setting("smtp_port", "587") or "587"),
        "user": await get_setting("smtp_user", "") or "",
        "password": await get_setting("smtp_password", "") or "",
        "to": await get_setting("smtp_to", "") or "",
    }
    if not config["to"]:
        return
    await send_email(config, event)


def register_email_hook():
    from comicfeed.hooks import bus
    bus.on("gallery.created", _on_event_send_email)
