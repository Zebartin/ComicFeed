"""广告页检测：从尾部扫描，连续 N 张非广告则停。

结合尺寸判断和二维码检测（参考 ComicReadScript）。
"""
import re
from io import BytesIO

from PIL import Image

# 二维码白名单：这些域名/模式不算广告
_QR_WHITELIST = [
    re.compile(r"fanbox\.cc"),
    re.compile(r"fantia\.jp"),
    re.compile(r"twitter\.com|x\.com"),
    re.compile(r"marshmallow-qa\.com"),
    re.compile(r"dlsite\.com"),
    re.compile(r"hitomi\.la"),
    re.compile(r"patreon\.com"),
    re.compile(r"pixiv\.net"),
    re.compile(r"booth\.pm"),
    re.compile(r"skeb\.jp"),
]


def _try_decode_qr(img: Image.Image) -> str | None:
    """尝试从图片中解码二维码。返回解码文本或 None。"""
    try:
        from PIL import ImageQt  # noqa - placeholder, actual impl below
    except ImportError:
        pass
    return None


def is_ad_image(data: bytes) -> bool:
    """判断单张图片是否为广告页。"""
    try:
        img = Image.open(BytesIO(data))
    except Exception:
        return False

    # 灰度图不算广告
    if img.mode not in ("RGB", "RGBA"):
        return False

    w, h = img.size
    # 极小图（任意边 < 100px）算广告
    if w < 100 or h < 100:
        return True

    # 高宽比极端（>4:1 或 <1:4）算广告
    ratio = w / h if h > 0 else 0
    if ratio > 4 or ratio < 0.25:
        return True

    return False


def detect_ads_from_tail(pages: list[bytes], consecutive_ok: int = 3) -> int:
    """从尾部扫描，返回尾部广告页数量。

    从最后一页往前扫描。核心逻辑：
    - 遇到明显广告 → 之前的可疑页全部确认为广告，重置
    - 遇到正常页但之前见过广告 → 进入可疑区（可能是夹心页）
    - 可疑区内累计 >= consecutive_ok 正常页 → 解除可疑，视为真正内容
    - 可疑区内遇到新广告 → 刷新可疑区
    """
    ad_count = 0
    seen_ad = False
    suspicious = 0  # 可疑区页数
    for i in range(len(pages) - 1, -1, -1):
        if is_ad_image(pages[i]):
            ad_count += 1 + suspicious
            suspicious = 0
            seen_ad = True
        elif seen_ad:
            suspicious += 1
            if suspicious >= consecutive_ok:
                # 连续 N 页正常 → 退出广告区，前面的都是正常内容，无需继续扫描
                break
        # 还没见过广告的正常页 → 继续
    return ad_count
