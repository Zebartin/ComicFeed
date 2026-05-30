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
    count = event.data.get("count", 0)
    failed = event.data.get("failed", [])
    failed_count = event.data.get("failed_count", 0)
    if count or failed_count:
        galleries = event.data.get("galleries", [])[:12]
        label = f"{count} 个成功" + (f" / {failed_count} 个失败" if failed_count else "")
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="font-family:system-ui,sans-serif;color:#333;max-width:600px;margin:0 auto">
<h2 style="color:#b8860b;border-bottom:1px solid #e5ded3;padding-bottom:8px">ComicFeed · 新下载</h2>
<p style="color:#666;font-size:14px">订阅: {event.data.get('subscription', '')} · {label}</p>
"""
        for g in galleries:
            cover = g.get('cover_url', '')
            web = g.get('web_url', '')
            pages = g.get('page_count', 0)
            title = g.get('title', '')[:80]
            html += f"""<table cellpadding="0" cellspacing="0" style="margin-bottom:12px;border:1px solid #e5ded3;border-radius:8px;overflow:hidden"><tr>
<td style="width:80px;vertical-align:top">{"<img src='"+cover+"' style='width:80px;height:auto;display:block'>" if cover else "<div style='width:80px;height:110px;background:#f0ebe0'></div>"}</td>
<td style="padding:8px 12px;vertical-align:top"><div style="font-size:10px;color:#b8860b;font-family:monospace">#{g.get('gallery_id','').split(':')[-1]}</div>
<div style="font-size:13px;font-weight:500;line-height:1.3">{title}</div>
<div style="font-size:11px;color:#999;margin-top:4px">{pages} 页</div>
{"<a href='"+web+"' style='font-size:11px;color:#b8860b;text-decoration:none'>在源站查看</a>" if web else ""}</td></tr></table>"""
        if count > 12:
            html += f"<p style='color:#999;font-size:12px'>... 等共 {count} 个画廊</p>"
        for f in failed[:5]:
            html += f"<p style='font-size:11px;color:#c0392b;margin:4px 0'>&#10007; {f.get('title','')[:60]} &mdash; {f.get('error','')[:100]}</p>"
        if failed_count > 5:
            html += f"<p style='font-size:11px;color:#999'>... 等共 {failed_count} 个失败</p>"
        html += f"<p style='color:#999;font-size:11px;margin-top:20px;border-top:1px solid #e5ded3;padding-top:10px'>由 ComicFeed 自动发送</p></body></html>"
        body = html
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(html, "html", "utf-8"))
    else:
        title = event.data.get("title", "")
        body = f"事件: {event.name}\n标题: {title}\n"
        for k, v in event.data.items():
            if k in ("title", "files"):
                continue
            body += f"{k}: {v}\n"
        if "files" in event.data:
            body += f"文件: {', '.join(event.data['files'][:5])}\n"
        msg = MIMEMultipart()
        msg.attach(MIMEText(body, "plain", "utf-8"))

    msg["Subject"] = subject
    msg["From"] = config.get("user", "")
    msg["To"] = config.get("to", "")

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
