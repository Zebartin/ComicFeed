import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote, urlparse

import httpx

from comicfeed.infrastructure.log import get

_log = get(__name__)

# 内嵌封面上限：超过则该图回退远程 URL
_COVER_MAX_BYTES = 300 * 1024
_COVER_REFERERS = {"i.pximg.net": "https://www.pixiv.net"}


def build_payload(event: dict) -> dict:
    """构建 webhook JSON 负载。event: {"name": str, "data": dict}"""
    payload = {"event": event["name"]}
    for k, v in event["data"].items():
        if isinstance(v, list) and len(v) > 5:
            payload[k] = v[:5]
            payload[f"{k}_count"] = len(v)
        else:
            payload[k] = v
    return payload


async def send_webhook(url: str, event: dict, _client=None):
    """发送 webhook POST 请求。"""
    payload = build_payload(event)
    if _client is not None:
        async with _client as client:
            await client.post(url, json=payload)
    else:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json=payload)


def _smtp_send(config: dict, msg: MIMEMultipart):
    """SMTP 传输（阻塞，跑在 to_thread）。"""
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


async def _fetch_cover_bytes(url: str) -> bytes:
    """服务端抓封面（pixiv 图床需要 Referer）。"""
    headers = {"User-Agent": "ComicFeed/1.0"}
    host = urlparse(url).hostname or ""
    ref = _COVER_REFERERS.get(host)
    if ref:
        headers["Referer"] = ref
    async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=headers) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


async def _make_cover(cover: str, public_domain: str, attachments: list, cid: str) -> str:
    """生成封面 <img> 标签。

    public_domain 非空 → 公网代理模式：指向自家 /api/cover；
    否则内嵌模式：服务端抓图 → CID 附件（失败/超限回退远程 URL）。
    """
    if not cover:
        return "<div style='width:80px;height:110px;background:#f0ebe0'></div>"
    img_style = "style='width:80px;height:auto;display:block'"
    if public_domain:
        domain = public_domain.strip().rstrip('/')
        if "://" not in domain:
            domain = f"https://{domain}"  # 缺协议时补 https（否则客户端会丢弃无 scheme 的 src）
        return f"<img src='{domain}/api/cover?url={quote(cover, safe='')}' {img_style}>"
    try:
        data = await _fetch_cover_bytes(cover)
    except Exception as e:
        _log.warning("封面抓取失败，回退远程 URL: %s - %r", cover, e)
        return f"<img src='{cover}' {img_style}>"
    if len(data) > _COVER_MAX_BYTES:
        _log.warning("封面超过内嵌上限(%dKB)，回退远程 URL: %s", len(data) // 1024, cover)
        return f"<img src='{cover}' {img_style}>"
    from email.mime.image import MIMEImage
    img = MIMEImage(data)
    img.add_header("Content-ID", f"<{cid}>")
    attachments.append(img)
    return f"<img src='cid:{cid}' {img_style}>"


async def send_email(config: dict, event: dict):
    """发送单事件邮件（测试通知等）。event: {"name": str, "data": dict}"""
    subject = f"[ComicFeed] {event['name']}"
    data = event.get("data", {})
    count = data.get("count", 0)
    failed = data.get("failed", [])
    failed_count = data.get("failed_count", 0)
    if count or failed_count:
        galleries = data.get("galleries", [])[:12]
        label = f"{count} 个成功" + (f" / {failed_count} 个失败" if failed_count else "")
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="font-family:system-ui,sans-serif;color:#333;max-width:600px;margin:0 auto">
<h2 style="color:#b8860b;border-bottom:1px solid #e5ded3;padding-bottom:8px">ComicFeed · 新下载</h2>
<p style="color:#666;font-size:14px">订阅: {data.get('subscription', '')} · {label}</p>
"""
        from comicfeed.infrastructure.config import get_setting
        public_domain = (await get_setting("cover_proxy_domain", "") or "")
        attachments = []
        for i, g in enumerate(galleries):
            cover = g.get('cover_url', '')
            cover_img = await _make_cover(cover, public_domain, attachments, f"cover{i}")
            web = g.get('web_url', '')
            pages = g.get('page_count', 0)
            title = g.get('title', '')[:80]
            html += f"""<table cellpadding="0" cellspacing="0" style="margin-bottom:12px;border:1px solid #e5ded3;border-radius:8px;overflow:hidden"><tr>
<td style="width:80px;vertical-align:top">{cover_img}</td>
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
        # related：内嵌封面与正文同组，cid: 引用才能被解析
        msg = MIMEMultipart("related")
        msg.attach(MIMEText(html, "html", "utf-8"))
        for att in attachments:
            msg.attach(att)
    else:
        title = data.get("title", "")
        body = f"事件: {event['name']}\n标题: {title}\n"
        for k, v in data.items():
            if k in ("title", "files"):
                continue
            body += f"{k}: {v}\n"
        if "files" in data:
            body += f"文件: {', '.join(data['files'][:5])}\n"
        msg = MIMEMultipart()
        msg.attach(MIMEText(body, "plain", "utf-8"))

    msg["Subject"] = subject
    msg["From"] = config.get("user", "")
    msg["To"] = config.get("to", "")

    await asyncio.to_thread(_smtp_send, config, msg)


async def send_digest_email(config: dict, digest: dict):
    """发送摘要邮件：按订阅分组的下载/失败列表。digest 由 services/digest.build_digest 生成。"""
    since = digest["since"]
    until = digest["until"]
    n_sub = len(digest["subscriptions"])
    label = f"{n_sub} 订阅 · {digest['total_count']} 下载"
    if digest["total_failed"]:
        label += f" / {digest['total_failed']} 失败"
    # until 是摘要窗口内最后一条下载事件的时间，与 since 一起构成统计范围
    window = f"统计范围：{since:%Y-%m-%d %H:%M} ~ {until:%Y-%m-%d %H:%M}"

    parts = [f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="font-family:system-ui,sans-serif;color:#333;max-width:600px;margin:0 auto">
<h2 style="color:#b8860b;border-bottom:1px solid #e5ded3;padding-bottom:8px">ComicFeed · 下载摘要</h2>
<p style="color:#666;font-size:14px">{label}</p>
<p style="color:#999;font-size:12px">{window}</p>
"""]
    from comicfeed.infrastructure.config import get_setting
    public_domain = (await get_setting("cover_proxy_domain", "") or "")
    attachments = []
    for g in digest["subscriptions"]:
        sub_label = f"{g['name']} · {g['count']} 个下载"
        if g["failed_count"]:
            sub_label += f" / {g['failed_count']} 个失败"
        parts.append(f"""<h3 style="font-size:14px;color:#b8860b;margin:20px 0 8px;border-bottom:1px solid #f0e8dc;padding-bottom:4px">{sub_label}</h3>""")
        for item in g["items"]:
            cover = item.get("cover_url", "")
            # cid 须在整封邮件内唯一（跨订阅分组），按已附加的封面数编号
            cover_img = await _make_cover(cover, public_domain, attachments, f"cover{len(attachments)}")
            web = item.get("web_url", "")
            pages = item.get("page_count", 0)
            title = (item.get("title", "") or "")[:80]
            gid = (item.get("gallery_id", "") or "").split(":")[-1]
            parts.append(f"""<table cellpadding="0" cellspacing="0" style="margin-bottom:10px;border:1px solid #e5ded3;border-radius:8px;overflow:hidden"><tr>
<td style="width:80px;vertical-align:top">{cover_img}</td>
<td style="padding:8px 12px;vertical-align:top"><div style="font-size:10px;color:#b8860b;font-family:monospace">#{gid}</div>
<div style="font-size:13px;font-weight:500;line-height:1.3">{title}</div>
<div style="font-size:11px;color:#999;margin-top:4px">{pages} 页</div>
{"<a href='"+web+"' style='font-size:11px;color:#b8860b;text-decoration:none'>在源站查看</a>" if web else ""}</td></tr></table>""")
        if g["count"] > len(g["items"]):
            parts.append(f"<p style='color:#999;font-size:12px'>... 等共 {g['count']} 个画廊</p>")
        for f in g["failed"]:
            parts.append(f"<p style='font-size:11px;color:#c0392b;margin:4px 0'>&#10007; {f['title'][:60]} &mdash; {f['error'][:100]}</p>")
        if g["failed_count"] > len(g["failed"]):
            parts.append(f"<p style='font-size:11px;color:#999'>... 等共 {g['failed_count']} 个失败</p>")
    parts.append("<p style='color:#999;font-size:11px;margin-top:20px;border-top:1px solid #e5ded3;padding-top:10px'>由 ComicFeed 自动发送</p></body></html>")

    msg = MIMEMultipart("related")
    msg.attach(MIMEText("".join(parts), "html", "utf-8"))
    for att in attachments:
        msg.attach(att)
    msg["Subject"] = f"[ComicFeed] 摘要 · {until.strftime('%Y-%m-%d')} · {n_sub} 订阅 · {digest['total_count']} 下载"
    msg["From"] = config.get("user", "")
    msg["To"] = config.get("to", "")

    await asyncio.to_thread(_smtp_send, config, msg)
