"""HTTP 请求重试：429 + 指数退避。"""
import asyncio

from comicfeed.infrastructure.log import get

_log = get(__name__)


async def retry_get(client, url: str, max_retries: int = 3, **kw):
    """GET 请求，遇 429 自动指数退避重试。网络异常也重试。"""
    for attempt in range(max_retries):
        try:
            resp = await client.get(url, **kw)
            if resp.status_code == 429:
                delay = _retry_delay(resp, attempt)
                _log.warning("429 限速(重试%d/%d): %s 等待 %.0fs", attempt + 1, max_retries, url, delay)
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt < max_retries - 1 and not _is_permanent(e):
                delay = 5 * (2 ** attempt)
                _log.warning("请求失败(重试%d/%d): %s - %r 等待 %.0fs", attempt + 1, max_retries, url, e, delay)
                await asyncio.sleep(delay)
                continue
            raise
    # 最后一次尝试也失败了
    resp = await client.get(url, **kw)
    resp.raise_for_status()
    return resp


def _retry_delay(resp, attempt: int) -> float:
    """从响应中提取 Retry-After，否则用指数退避 5s/10s/20s。"""
    try:
        return float(resp.headers.get("Retry-After", ""))
    except (ValueError, TypeError):
        return 5 * (2 ** attempt)


def _is_permanent(e: Exception) -> bool:
    """不应重试的错误（404, 认证失败等）。"""
    status = getattr(getattr(e, "response", None), "status_code", None)
    return status in (400, 401, 403, 404, 405)
