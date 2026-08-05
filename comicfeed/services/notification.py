"""通知服务：源错误即时 Webhook。下载摘要见 services/digest.py。"""
from comicfeed.infrastructure.config import get_setting
from comicfeed.infrastructure.log import get
from comicfeed.infrastructure.notifications import send_webhook

_log = get(__name__)


async def notify_source_error(data: dict):
    """源错误通知（即时，不进 digest）。"""
    event = {"name": "source.error", "data": data}

    # Webhook
    try:
        url = await get_setting("webhook_url", "")
        if url:
            await send_webhook(url, event)
    except Exception:
        _log.exception("Webhook 通知失败")
