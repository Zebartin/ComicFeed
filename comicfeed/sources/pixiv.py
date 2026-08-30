"""pixiv 源插件：画师/榜单 → Gallery、作品 → 页面。

凭 refresh_token 访问 app-api（OAuth 2.0，X-Client-Time/X-Client-Hash 签名）。
API 与图片请求需 iOS App 身份，图片下载需 Referer。
"""

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

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


# 动图转换（下载阶段执行）：check 时登记作品信息、download 时转换并缓存产物
_webp_cache: dict[str, tuple[float, bytes]] = {}
_webp_ttl = 3000.0
_ugoira_items: dict[str, tuple[float, dict]] = {}
_ugoira_ttl = 3600.0
_skip_notes: list[dict] = []

# 429 全局冷却：收到限流后所有 API 请求先等待再发
_cooldown_until: float = 0.0


class PixivSource(BaseSource):
    key = "pixiv"
    name = "Pixiv"
    version = "0.1.0"
    domains = ["app-api.pixiv.net"]
    auth_schema = AuthSchema.TOKEN
    supports_search_mode = False  # 画师/榜单为集合模型，仅 SPECIFIC_GALLERY 语义

    _BASE = "https://app-api.pixiv.net"
    _AUTH = "https://oauth.secure.pixiv.net"  # token 端点在 oauth 域名，不在 app-api
    _CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
    _CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
    _HASH_SECRET = "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c"
    _UA = "PixivIOSApp/7.19.1 (iOS 16.6; iPhone14,5)"
    _RANK_MODES = {
        "daily": "day", "weekly": "week", "monthly": "month",
        "male": "day_male", "female": "day_female", "rookie": "week_rookie",
        "daily_r18": "day_r18", "weekly_r18": "week_r18",
        "male_r18": "day_male_r18", "female_r18": "day_female_r18",
        "weekly_r18g": "week_r18g",
        "daily_ai": "day_ai", "weekly_ai": "week_ai", "monthly_ai": "month_ai",
        "daily_r18_ai": "day_r18_ai", "weekly_r18_ai": "week_r18_ai",
        "monthly_r18_ai": "month_r18_ai",
    }
    _RANK_MODE_LABELS = {
        "daily": "日", "weekly": "周", "monthly": "月", "rookie": "新人",
        "male": "男性", "female": "女性",
        "daily_r18": "日R-18", "weekly_r18": "周R-18",
        "male_r18": "男性R-18", "female_r18": "女性R-18",
        "weekly_r18g": "周R-18G",
        "daily_ai": "日AI", "weekly_ai": "周AI", "monthly_ai": "月AI",
        "daily_r18_ai": "日R-18AI", "weekly_r18_ai": "周R-18AI",
        "monthly_r18_ai": "月R-18AI",
    }
    _CONTENT_LABELS = {"illust": "插画", "manga": "漫画", "ugoira": "动图", "all": "综合"}

    def __init__(self, proxy=None, credentials=None,
                 transport: httpx.AsyncBaseTransport | None = None, time_fn=None):
        super().__init__(proxy=proxy, credentials=credentials)
        self._transport = transport
        self._time = time_fn or time.time
        self._access_token = ""
        self._expires_at = 0.0
        self._next_url = ""  # 搜索游标翻页（与 exhentai 同机制）

    def get_config_schema(self) -> list[dict]:
        return [
            {"key": "proxy", "label": "代理", "type": "text",
             "placeholder": "空=全局, -=直连", "hint": "留空沿用全局代理"},
            {"key": "throttle", "label": "请求间隔（秒）", "type": "text",
             "placeholder": "0.1", "hint": "每页下载后的等待间隔，防限流；0 或 - 表示不等待"},
            {"key": "refresh_token", "label": "refresh_token", "type": "password",
             "credential": True, "placeholder": "pixiv 的 refresh_token（OAuth）",
             "hint": "长期凭证，加密存储。R-18 内容显示取决于账号设置：pixiv 设置 → 浏览与显示 → 显示敏感内容（未开启时 R-18 作品/榜单会被静默过滤）。"},
            {"key": "max_mb", "label": "图片大小上限（MB）", "type": "text",
             "placeholder": "0", "hint": "单图超过此大小时程序内压缩（降质重编码/降分辨率，尽力压缩不保证达标）；0 或留空 = 不压缩；动图（ugoira）不受影响"},
        ]

    def parse_url(self, url: str) -> str | None:
        m = re.match(r"https?://(?:www\.)?pixiv\.net/(?:en/)?users/(\d+)", url)
        if m:
            return f"pixiv:{m.group(1)}"
        u = urlparse(url)
        if u.hostname not in ("www.pixiv.net", "pixiv.net") or u.path != "/ranking.php":
            return None
        qs = parse_qs(u.query)
        mode = (qs.get("mode") or [""])[0]
        content = (qs.get("content") or [""])[0]
        if not mode or not content:
            return None
        return f"pixiv:ranking_{mode}_{content}"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            proxy=self.proxy,
            timeout=30,
            headers={"User-Agent": self._UA, "Accept-Language": "zh-hans"},
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
            f"{self._AUTH}/auth/token",
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

    # --- 作品/集合构建 ---

    @staticmethod
    def _max_bytes_from_cfg(cfg: dict) -> int:
        try:
            mb = float(cfg.get("max_mb") or 0)
        except (ValueError, TypeError):
            return 0
        return int(mb * 1024 * 1024) if mb > 0 else 0

    @staticmethod
    def _compress_image(data: bytes, limit: int) -> bytes:
        """超限图片程序内压缩：JPEG 降质重编码（85/75/65），仍超限则按比例降像素（0.9→0.6，长边≥1200）。

        RGBA PNG（含透明）不动；RGB PNG 转 JPEG；无法解码原样返回。尽力压缩，不保证严格达标。
        """
        import io
        from PIL import Image
        if len(data) <= limit:
            return data
        try:
            im = Image.open(io.BytesIO(data))
            im.load()
        except Exception:
            return data
        fmt = im.format
        best = data
        if fmt == "PNG":
            if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                # 透明 PNG：不转 JPEG（保 alpha），只按比例降像素，仍存 PNG
                if im.mode != "RGBA":
                    im = im.convert("RGBA")
                w, h = im.size
                long_side = max(w, h)
                for scale in (0.9, 0.8, 0.7, 0.6, 0.5):
                    target = int(long_side * scale)
                    if target < 600:
                        break
                    ratio = target / long_side
                    scaled = im.resize((max(1, int(w * ratio)), max(1, int(h * ratio))),
                                       Image.LANCZOS)
                    buf = io.BytesIO()
                    scaled.save(buf, "PNG", optimize=True)
                    out = buf.getvalue()
                    if len(out) <= limit:
                        return out
                    if len(out) < len(best):
                        best = out
                return best
            im = im.convert("RGB")
        elif fmt != "JPEG":
            return data
        # 质量阶梯（全分辨率，PNG 转 JPEG 同样适用）
        for quality in (85, 75, 65):
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=quality, optimize=True)
            out = buf.getvalue()
            if len(out) <= limit:
                return out
            if len(out) < len(best):
                best = out
        # 像素阶梯：等比缩小 0.9 → 0.5，长边不低于 600
        w, h = im.size
        long_side = max(w, h)
        for scale in (0.9, 0.8, 0.7, 0.6, 0.5):
            target = int(long_side * scale)
            if target < 600:
                break
            ratio = target / long_side
            scaled = im.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), Image.LANCZOS)
            buf = io.BytesIO()
            scaled.save(buf, "JPEG", quality=85, optimize=True)
            out = buf.getvalue()
            if len(out) <= limit:
                return out
            if len(out) < len(best):
                best = out
        return best

    @staticmethod
    def _throttle_from_cfg(cfg: dict) -> float:
        try:
            v = str(cfg.get("throttle") or "").strip()
        except (ValueError, TypeError):
            return 0.1
        if v in ("-", "0"):
            return 0.0
        if not v:
            return 0.1
        try:
            return float(v)
        except ValueError:
            return 0.1

    async def _respect_cooldown(self) -> None:
        wait = _cooldown_until - time.time()
        if wait > 0:
            await asyncio.sleep(wait)

    async def _api_get(self, client: httpx.AsyncClient, url: str, **kw):
        """API GET：尊重全局冷却，429 指数退避重试，触发限流后设置冷却。"""
        from comicfeed.infrastructure.http_retry import retry_get
        await self._respect_cooldown()
        try:
            return await retry_get(client, url, **kw)
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 429:
                global _cooldown_until
                _cooldown_until = time.time() + 30
            raise

    @staticmethod
    def _has_cjk(s: str) -> bool:
        return any("\u4e00" <= ch <= "\u9fff" for ch in s)

    _MILESTONE_USERS = re.compile(r"\d+\s*users入り$", re.IGNORECASE)  # 原神10000users入り
    _MILESTONE_FAV = re.compile(r"^\D*\d+\s*收藏$")  # 翻译形态：原神10000收藏

    @classmethod
    def _pick_tag(cls, t: dict) -> str | None:
        """官方中文优先；官方翻译是罗马音/英文（无汉字）时回退日文原文；里程碑标签丢弃。"""
        name = t.get("name") or ""
        translated = t.get("translated_name") or ""
        if (cls._MILESTONE_USERS.search(name) or cls._MILESTONE_FAV.match(name)
                or cls._MILESTONE_FAV.match(translated)):
            return None
        if not name:
            return translated or None
        if not translated:
            return name
        if cls._has_cjk(translated):
            return translated
        if cls._has_cjk(name):
            return name  # 罗马音/英文翻译不如原文可读
        return name  # 两边都无汉字（如 ASCII 标签），用原文

    @staticmethod
    def _match_content(item: dict, content: str) -> bool:
        if content == "all":
            return True  # 综合榜：全部类型混排
        itype = item.get("type", "")
        if content == "ugoira":
            return itype == "ugoira"
        if content == "manga":
            return itype == "illust" and int(item.get("page_count") or 0) > 1
        # content=illust：插画（含多页）+ 动图混排（动图转 WebP 进同一卷）
        return itype in ("illust", "ugoira")

    def _work_page_ids(self, item: dict) -> list[str]:
        """作品的页 ID 列表（动图为单页 webp id）。用于检查阶段的按作品去重。"""
        wid = str(item.get("id", ""))
        if item.get("type") == "ugoira":
            return [f"{wid}_webp"]
        return [pid for pid, _ in self._work_pages(item)]

    def _work_pages(self, item: dict) -> list[tuple[str, str]]:
        """作品的全部原图页：[(page_native_id, url)]。"""
        wid = str(item.get("id", ""))
        pages = []
        metas = item.get("meta_pages") or []
        if metas:
            for i, meta in enumerate(metas):
                url = (meta.get("image_urls") or {}).get("original", "")
                if url:
                    pages.append((f"{wid}_p{i}", url))
        else:
            single = item.get("meta_single_page") or {}
            url = single.get("original_image_url", "")
            if url:
                pages.append((f"{wid}_p0", url))
        return pages

    async def _convert_ugoira(self, client: httpx.AsyncClient, item: dict) -> bytes:
        """动图 → 动画 WebP（下载阶段调用）。失败抛 RuntimeError，画廊下载失败可重试。"""
        import io
        import zipfile
        from PIL import Image
        from comicfeed.infrastructure.log import get
        _log = get(__name__)
        wid = str(item.get("id", ""))
        title = item.get("title", "") or wid
        try:
            resp = await client.get(f"{self._BASE}/v1/ugoira/metadata", params={"illust_id": wid},
                                    headers={"Authorization": f"Bearer {self._access_token}"})
            if resp.status_code != 200:
                raise PixivAuthError(f"元数据 HTTP {resp.status_code}")
            meta = resp.json().get("ugoira_metadata") or {}
            frames = meta.get("frames") or []
            durations = [int(f.get("delay") or 0) for f in frames]
            zurls = meta.get("zip_urls") or {}
            # 三级帧源：large zip → img-original 原始帧 → medium zip
            images, source_desc = None, ""
            if zurls.get("large"):
                images, source_desc = await self._fetch_ugoira_zip(client, wid, frames, zurls["large"])
            if images is None:
                images, source_desc = await self._fetch_ugoira_originals(client, item, frames)
            if images is None and zurls.get("medium"):
                images, source_desc = await self._fetch_ugoira_zip(client, wid, frames, zurls["medium"])
            if images is None:
                raise PixivAuthError("动图帧获取失败（zip 与原始帧均不可用）")
            _log.info("pixiv 动图帧包: work=%s %s", wid, source_desc)
            if len(images) != len(durations):
                durations = durations[:len(images)]
            buf = io.BytesIO()
            if len(images) == 1:
                images[0].save(buf, "WEBP")
            else:
                images[0].save(buf, "WEBP", save_all=True, append_images=images[1:],
                               duration=durations, loop=0)
            data = buf.getvalue()
            _webp_cache[wid] = (time.time(), data)
            _log.info("pixiv 动图转换完成: work=%s 帧=%d 首帧=%dx%d webp=%dKB",
                      wid, len(images), images[0].width, images[0].height, len(data) // 1024)
            return data
        except Exception as e:
            _log.warning("pixiv 动图转换失败: %s %s - %r", wid, title, e)
            raise RuntimeError(f"动图转换失败({title}): {e}") from e

    async def _fetch_ugoira_zip(self, client: httpx.AsyncClient, wid: str,
                                frames: list[dict], zip_url: str):
        """下载 ugoira 帧 zip 并按 metadata 顺序解帧。失败返回 (None, "")。"""
        import io
        import zipfile
        from PIL import Image
        from comicfeed.infrastructure.log import get
        _log = get(__name__)
        try:
            zresp = await client.get(zip_url, headers={"Referer": "https://app-api.pixiv.net"})
            zresp.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(zresp.content)) as zf:
                images = []
                for fmeta in frames:
                    fname = fmeta.get("file", "")
                    if not fname:
                        continue
                    images.append(Image.open(io.BytesIO(zf.read(fname))).convert("RGB"))
            return images, zip_url.rsplit("/", 1)[-1]
        except Exception as e:
            _log.warning("pixiv 动图帧包拉取失败(尝试下一方案): work=%s %s - %r",
                         wid, zip_url.rsplit("/", 1)[-1], e)
            return None, ""

    async def _fetch_ugoira_originals(self, client: httpx.AsyncClient, item: dict,
                                      frames: list[dict]):
        """large 包缺失时逐帧下载 img-original 原始帧（{id}_ugoira{n} 命名规律）。失败返回 (None, "")。"""
        import io
        from PIL import Image
        from comicfeed.infrastructure.log import get
        _log = get(__name__)
        first = (item.get("meta_single_page") or {}).get("original_image_url") or ""
        m = re.search(r"_ugoira\d+(\.\w+)$", first)
        if not m or not frames:
            return None, ""
        base, ext = first[:m.start()], m.group(1)
        wid = str(item.get("id", ""))
        images = []
        for i in range(len(frames)):
            url = f"{base}_ugoira{i}{ext}"
            try:
                r = await client.get(url, headers={"Referer": "https://app-api.pixiv.net"})
                r.raise_for_status()
                images.append(Image.open(io.BytesIO(r.content)).convert("RGB"))
            except Exception as e:
                _log.warning("pixiv 动图原始帧拉取失败(尝试下一方案): work=%s frame=%d - %r", wid, i, e)
                return None, ""
        return images, f"原始帧×{len(images)}"

    def pop_download_notes(self) -> list[dict]:
        """下载服务调用：取走并清空本源积累的跳过说明（一次性消费）。"""
        notes, _skip_notes[:] = list(_skip_notes), []
        return notes

    @staticmethod
    def _split_ranking_id(gallery_id: str) -> tuple[str, str]:
        """ranking_{mode}_{content} → (mode, content)。content 为已知后缀，mode 可含下划线。"""
        rest = gallery_id[len("ranking_"):]
        for c in ("all", "illust", "manga", "ugoira"):
            suffix = "_" + c
            if rest.endswith(suffix):
                return rest[:-len(suffix)], c
        raise PixivAuthError(f"不支持的榜单 ID: {gallery_id}")

    @classmethod
    def _collection_title(cls, gallery_id: str) -> str:
        mode, content = cls._split_ranking_id(gallery_id)
        c = cls._CONTENT_LABELS.get(content, content)
        m = cls._RANK_MODE_LABELS.get(mode, mode)
        return f"Pixiv {c}{m}榜"

    async def _build_collection_detail(self, gallery_id: str,
                                       items: list[dict], content: str) -> GalleryDetail:
        from comicfeed.infrastructure.log import get
        _log = get(__name__)
        page_ids, page_urls, tags, writers = [], [], set(), set()
        page_tags = []
        cover_url = ""
        is_user = gallery_id.isdigit()
        for item in items:
            # 诊断：输出原始标签对，供人工核对官方翻译策略（name=translated_name）
            _log.debug("pixiv 标签明细 gallery=%s work=%s: %s", gallery_id, item.get("id"),
                      " | ".join(f"{t.get('name')}={t.get('translated_name')}"
                                 for t in (item.get("tags") or [])) or "(无标签)")
            work_tags = sorted(t for t in (self._pick_tag(t) for t in item.get("tags", [])) if t)
            tags.update(work_tags)
            if not cover_url:
                cover_url = (item.get("image_urls") or {}).get("medium", "")
            if is_user:
                writers.add((item.get("user") or {}).get("name", ""))
            if item.get("type") == "ugoira":
                # 转换推迟到下载阶段：此处只登记作品信息 + 页标记
                wid = str(item.get("id", ""))
                _ugoira_items[wid] = (time.time(), item)
                page_ids.append(f"{wid}_webp")
                page_urls.append(f"pixiv-webp:{wid}")
                page_tags.append(work_tags)
                continue
            for pid, purl in self._work_pages(item):
                page_ids.append(pid)
                page_urls.append(purl)
                page_tags.append(work_tags)
        if is_user:
            name = next(((it.get("user") or {}).get("name", "") for it in items), "")
            title = name or gallery_id
        else:
            title = self._collection_title(gallery_id)
        return GalleryDetail(
            native_id=gallery_id,
            title=title,
            cover_url=cover_url,
            web_url="",
            page_urls=page_urls,
            page_native_ids=page_ids,
            tags=sorted(t for t in tags if t),
            writers=sorted(w for w in writers if w),
            reported_pages=len(page_ids),
            display_id="" if not is_user else None,  # 榜单为非数字 ID：文件名/ComicInfo 省略
            keep_page_names=True,  # 保留 pixiv 原始页面文件名（如 149035907_p2）
            page_tags=page_tags,
        )

    async def _fetch_ranking_items(self, client: httpx.AsyncClient, gallery_id: str, content: str) -> list[dict]:
        mode, _content = self._split_ranking_id(gallery_id)
        app_mode = self._RANK_MODES.get(mode)
        if not app_mode:
            raise PixivAuthError(f"不支持的榜单模式: {mode}")
        resp = await self._api_get(client, f"{self._BASE}/v1/illust/ranking",
                                    params={"mode": app_mode},
                                    headers={"Authorization": f"Bearer {self._access_token}"})
        return [it for it in (resp.json().get("illusts") or []) if self._match_content(it, content)]

    async def _fetch_all_user_items(self, client: httpx.AsyncClient, uid: str, max_pages: int) -> list[dict]:
        """翻页收集画师作品。max_pages: 0=只翻第 1 页；1=翻到底；≥2=上限 N 页。"""
        items, fetched = [], 0
        offset = 0
        while True:
            page_items, has_next = await self._fetch_user_items(client, uid, offset)
            items.extend(page_items)
            fetched += 1
            if not has_next:
                break
            if max_pages == 0:
                break
            if max_pages >= 2 and fetched >= max_pages:
                break
            await asyncio.sleep(0.5)  # 翻页节流
            offset += 30
        return items

    async def _fetch_user_items(self, client: httpx.AsyncClient, uid: str, offset: int = 0):
        resp = await self._api_get(client, f"{self._BASE}/v1/user/illusts",
                                    params={"user_id": uid, "offset": offset},
                                    headers={"Authorization": f"Bearer {self._access_token}"})
        j = resp.json()
        return j.get("illusts") or [], bool(j.get("next_url"))

    def _apply_work_filters(self, items: list[dict], filters_json: str) -> list[dict]:
        """订阅筛选条件按作品逐个应用（收藏数/页数/上传日期），不达标的作品不收录。"""
        if not filters_json:
            return items
        try:
            rules = json.loads(filters_json)
        except (json.JSONDecodeError, TypeError):
            return items
        if not rules:
            return items
        from comicfeed.services.subscription import _matches_filter
        kept = []
        for it in items:
            g = GallerySummary(
                native_id=str(it.get("id", "")),
                title=it.get("title", ""),
                cover_url="",
                page_count=int(it.get("page_count") or 0),
                num_favorites=int(it.get("total_bookmarks") or 0),
                upload_date=(it.get("create_date") or "")[:10],
            )
            if _matches_filter(g, rules):
                kept.append(it)
        return kept

    @classmethod
    def _ranking_url(cls, gallery_id: str) -> str:
        mode, content = cls._split_ranking_id(gallery_id)
        return f"https://www.pixiv.net/ranking.php?mode={mode}&content={content}"

    async def get_gallery(self, gallery_id: str, gallery_url: str = "") -> GalleryDetail:
        from comicfeed.infrastructure import gallery_cache as _gc
        upd = _gc.update_cache_get(gallery_id)
        if upd:
            return upd
        key = gallery_url or gallery_id
        cached = _gc.cache_get(key)
        if cached:
            return cached
        async with self._client() as client:
            await self._ensure_token(client)
            if gallery_id.startswith("ranking_"):
                _, content = self._split_ranking_id(gallery_id)
                items = await self._fetch_ranking_items(client, gallery_id, content)
                detail = await self._build_collection_detail(gallery_id, items, content)
            elif gallery_id.isdigit():
                items = await self._fetch_all_user_items(client, gallery_id, 1)
                items = sorted(items, key=lambda it: str(it.get("id", "")).zfill(12))
                detail = await self._build_collection_detail(gallery_id, items, "illust")
            else:
                raise NotImplementedError("pixiv 作品详情由后续工单实现")
        detail.web_url = gallery_url or (self._ranking_url(gallery_id)
                                         if gallery_id.startswith("ranking_") else "")
        _gc.cache_set(key, detail)
        return detail

    def _updates_from(self, detail: GalleryDetail, old_ids, gallery_url: str = "") -> UpdateResult:
        from comicfeed.infrastructure import gallery_cache as _gc
        old = set(old_ids or [])
        keep_idx = [i for i, pid in enumerate(detail.page_native_ids) if pid not in old]
        if not keep_idx:
            return UpdateResult()
        filtered = GalleryDetail(
            native_id=detail.native_id, title=detail.title, cover_url=detail.cover_url,
            web_url=gallery_url or detail.web_url,
            page_urls=[detail.page_urls[i] for i in keep_idx],
            page_native_ids=[detail.page_native_ids[i] for i in keep_idx],
            tags=list(detail.tags), writers=list(detail.writers),
            upload_date=detail.upload_date, reported_pages=len(keep_idx),
            num_favorites=detail.num_favorites, display_id=detail.display_id,
            keep_page_names=detail.keep_page_names,
            page_tags=[detail.page_tags[i] for i in keep_idx] if detail.page_tags else [],
        )
        _gc.update_cache_set(detail.native_id, filtered)
        return UpdateResult(has_updates=True, gallery=GallerySummary(
            native_id=detail.native_id, title=detail.title, cover_url=detail.cover_url,
            web_url=filtered.web_url, page_count=len(keep_idx), tags=list(detail.tags),
            new_page_ids=[detail.page_native_ids[i] for i in keep_idx],
            detail=filtered,
        ))

    async def check_updates(self, gallery_id: str, last_known: dict, gallery_url: str = "") -> UpdateResult:
        old_ids = last_known.get("page_ids") or []
        old = set(old_ids)
        max_pages = int(last_known.get("max_pages") or 0)
        filters = last_known.get("filters") or ""
        async with self._client() as client:
            await self._ensure_token(client)
            if gallery_id.isdigit():
                if old_ids:
                    items, _ = await self._fetch_user_items(client, gallery_id)
                else:
                    items = await self._fetch_all_user_items(client, gallery_id, max_pages)
                items = [it for it in items
                         if any(pid not in old for pid in self._work_page_ids(it))]
                items = self._apply_work_filters(items, filters)
                items = sorted(items, key=lambda it: str(it.get("id", "")).zfill(12))
                detail = await self._build_collection_detail(gallery_id, items, "illust")
            elif gallery_id.startswith("ranking_"):
                _, content = self._split_ranking_id(gallery_id)
                items = await self._fetch_ranking_items(client, gallery_id, content)
                items = [it for it in items
                         if any(pid not in old for pid in self._work_page_ids(it))]
                items = self._apply_work_filters(items, filters)
                detail = await self._build_collection_detail(gallery_id, items, content)
            else:
                raise NotImplementedError(f"不支持的 pixiv 画廊 ID: {gallery_id}")
        return self._updates_from(detail, old_ids, gallery_url)

    async def download_pages(self, gallery_id: str, page_range: slice, gallery_url: str = "",
                             detail: GalleryDetail | None = None,
                             on_page: Callable[[], None] | None = None) -> list[bytes]:
        from comicfeed.infrastructure.config import get_setting, get_source_config
        from comicfeed.infrastructure.http_retry import retry_get
        from comicfeed.infrastructure.log import get
        _log = get(__name__)
        _retry = int(await get_setting("download_retry") or 3)
        _cfg = await get_source_config(self.key)
        _throttle = self._throttle_from_cfg(_cfg)
        _max_bytes = self._max_bytes_from_cfg(_cfg)
        if detail is None:
            detail = await self.get_gallery(gallery_id, gallery_url=gallery_url)
        urls = detail.page_urls[page_range]
        headers = {"Referer": "https://app-api.pixiv.net", "User-Agent": self._UA}
        async with httpx.AsyncClient(proxy=self.proxy, timeout=30, follow_redirects=True,
                                     headers=headers, transport=self._transport) as client:
            results = []
            for i, url in enumerate(urls):
                if url.startswith("pixiv-webp:"):
                    wid = url.split(":", 1)[1]
                    entry = _webp_cache.get(wid)
                    if entry and time.time() - entry[0] < _webp_ttl:
                        data = entry[1]
                    else:
                        it = _ugoira_items.get(wid)
                        if not it or time.time() - it[0] >= _ugoira_ttl:
                            raise RuntimeError(f"动图信息已过期，请重新检查订阅: {wid}")
                        await self._ensure_token(client)
                        data = await self._convert_ugoira(client, it[1])
                        _webp_cache[wid] = (time.time(), data)
                    results.append(data)
                    if on_page:
                        on_page()
                else:
                    try:
                        resp = await retry_get(client, url, max_retries=_retry)
                    except Exception as e:
                        _log.error("下载图片失败(重试%d次): gallery=%s page=%d - %r",
                                   _retry, gallery_id, page_range.start + i + 1, e)
                        raise
                    data = resp.content
                    if _max_bytes > 0 and len(data) > _max_bytes:
                        compressed = self._compress_image(data, _max_bytes)
                        if len(compressed) < len(data):
                            _log.info("pixiv 图片压缩: %s %dKB → %dKB", url,
                                      len(data) // 1024, len(compressed) // 1024)
                        data = compressed
                    results.append(data)
                    if on_page:
                        on_page()
                if _throttle > 0:
                    await asyncio.sleep(_throttle)
        return results

    # --- 搜索页透传（07） ---

    _SORTS = {"date": "date_desc", "date_desc": "date_desc", "date_asc": "date_asc"}

    def get_sort_options(self) -> list[dict]:
        return [
            {"value": "date_desc", "label": "最新"},
            {"value": "date_asc", "label": "最旧"},
        ]

    async def search(self, query: str, page: int, sort: str = "date") -> SearchResult:
        async with self._client() as client:
            await self._ensure_token(client)
            if page > 1 and self._next_url:
                url, params = self._next_url, None
            else:
                url = f"{self._BASE}/v1/search/illust"
                params = {"word": query, "sort": self._SORTS.get(sort, "date_desc")}
                if page > 1:
                    params["offset"] = (page - 1) * 30
            resp = await client.get(url, params=params,
                                    headers={"Authorization": f"Bearer {self._access_token}"})
            if resp.status_code != 200:
                raise PixivAuthError(f"搜索失败: HTTP {resp.status_code}")
            data = resp.json()
            self._next_url = data.get("next_url") or ""
            return self._parse_search(data, page)

    def _parse_search(self, data: dict, page: int) -> SearchResult:
        from comicfeed.io.cbz import normalize_title
        items = []
        for it in data.get("illusts") or []:
            tags = [self._pick_tag(t) for t in (it.get("tags") or [])]
            items.append(GallerySummary(
                native_id=str(it.get("id", "")),
                title=normalize_title(it.get("title", "")),
                cover_url=(it.get("image_urls") or {}).get("medium", ""),
                web_url=f"https://www.pixiv.net/artworks/{it.get('id', '')}",
                page_count=int(it.get("page_count") or 0),
                num_favorites=int(it.get("total_bookmarks") or 0),
                tags=[t for t in tags if t],
            ))
        return SearchResult(items=items, total_pages=0, current_page=page, next_url=self._next_url)
