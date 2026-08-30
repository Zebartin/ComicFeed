"""pixiv 源插件：画师/榜单 → Gallery、作品 → 页面。

凭 refresh_token 访问 app-api（OAuth 2.0，X-Client-Time/X-Client-Hash 签名）。
API 与图片请求需 iOS App 身份，图片下载需 Referer。
"""

import hashlib
import time
from collections.abc import Callable

import httpx

from comicfeed.sources.base import (
    AuthSchema,
    BaseSource,
    GalleryDetail,
    GallerySummary,
    SearchResult,
    UpdateResult,
)


class PixivAuthError(Exception):
    """refresh_token 无效、过期或未配置。"""


class PixivSource(BaseSource):
    key = "pixiv"
    name = "Pixiv"
    version = "0.1.0"
    domains = ["app-api.pixiv.net"]
    auth_schema = AuthSchema.TOKEN

    _BASE = "https://app-api.pixiv.net"
    _CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
    _CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
    _HASH_SECRET = "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c"
    _UA = "PixivIOSApp/7.19.1 (iOS 16.6; iPhone14,5)"

    def __init__(self, proxy=None, credentials=None,
                 transport: httpx.AsyncBaseTransport | None = None, time_fn=None):
        super().__init__(proxy=proxy, credentials=credentials)
        self._transport = transport
        self._time = time_fn or time.time
        self._access_token = ""
        self._expires_at = 0.0

    def get_config_schema(self) -> list[dict]:
        return [
            {"key": "proxy", "label": "代理", "type": "text",
             "placeholder": "空=全局, -=直连", "hint": "留空沿用全局代理"},
            {"key": "refresh_token", "label": "refresh_token", "type": "password",
             "credential": True, "placeholder": "pixiv 的 refresh_token（OAuth）",
             "hint": "长期凭证，加密存储。R-18 内容显示取决于账号设置：pixiv 设置 → 浏览与显示 → 显示敏感内容（未开启时 R-18 作品/榜单会被静默过滤）。"},
        ]

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            proxy=self.proxy,
            timeout=30,
            headers={"User-Agent": self._UA},
            transport=self._transport,
        )

    def _auth_headers(self) -> dict[str, str]:
        ts = str(int(self._time()))
        return {"X-Client-Time": ts,
                "X-Client-Hash": hashlib.md5((ts + self._HASH_SECRET).encode("utf-8")).hexdigest()}

    async def _refresh_token(self, client: httpx.AsyncClient) -> None:
        rt = self.credentials.get("refresh_token", "")
        if not rt:
            raise PixivAuthError("未配置 refresh_token，请在源配置中填写")
        resp = await client.post(
            f"{self._BASE}/auth/token",
            data={"client_id": self._CLIENT_ID, "client_secret": self._CLIENT_SECRET,
                  "grant_type": "refresh_token", "refresh_token": rt, "get_secure_url": "1"},
            headers=self._auth_headers(),
        )
        if resp.status_code != 200:
            raise PixivAuthError("refresh_token 无效或已过期，请重新获取")
        data = resp.json()
        token = data.get("access_token", "")
        if not token:
            raise PixivAuthError("token 响应缺少 access_token")
        self._access_token = token
        self._expires_at = self._time() + float(data.get("expires_in", 3600)) - 60

    async def _ensure_token(self, client: httpx.AsyncClient) -> None:
        if not self._access_token or self._time() >= self._expires_at:
            await self._refresh_token(client)

    async def test_connection(self) -> tuple[bool, str]:
        async with self._client() as client:
            try:
                await self._ensure_token(client)
                resp = await client.get(f"{self._BASE}/v1/illust/ranking", params={"mode": "day"},
                                        headers={"Authorization": f"Bearer {self._access_token}"})
                if resp.status_code == 200:
                    return True, "连接成功"
                return False, f"API 返回 HTTP {resp.status_code}"
            except PixivAuthError as e:
                return False, str(e)
            except Exception as e:
                return False, f"连接失败: {e}"

    # --- 以下方法由后续工单实现（02/03/04/05/06/07） ---

    async def search(self, query: str, page: int, sort: str = "date") -> SearchResult:
        raise NotImplementedError

    async def get_gallery(self, gallery_id: str, gallery_url: str = "") -> GalleryDetail:
        raise NotImplementedError

    async def download_pages(self, gallery_id: str, page_range: slice, gallery_url: str = "",
                             detail: GalleryDetail | None = None,
                             on_page: Callable[[], None] | None = None) -> list[bytes]:
        raise NotImplementedError

    async def check_updates(self, gallery_id: str, last_known: dict, gallery_url: str = "") -> UpdateResult:
        raise NotImplementedError
