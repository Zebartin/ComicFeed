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


def _decode_qr(img: Image.Image) -> str | None:
    """尝试从图片中解码二维码。返回解码文本或 None。"""
    try:
        from pyzbar.pyzbar import decode
        results = decode(img)
        if results:
            text = results[0].data.decode("utf-8", errors="replace")
            return text.strip()
    except Exception:
        pass
    return None


def _has_ad_qr(img: Image.Image) -> bool:
    """检查图片是否含推广二维码。有 QR 码且不在白名单 = 广告。"""
    text = _decode_qr(img)
    if not text:
        return False
    # 白名单 URL → 不是广告
    if any(p.search(text) for p in _QR_WHITELIST):
        return False
    return True


def is_ad_image(data: bytes) -> bool:
    """判断单张图片是否为广告页。"""
    try:
        img = Image.open(BytesIO(data))
    except Exception as e:
        print(e)
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

    # 尺寸正常，检查是否有推广二维码
    if _has_ad_qr(img):
        return True

    return False


def detect_ads_from_tail(pages: list[bytes], consecutive_ok: int = 3) -> int:
    """从尾部扫描，返回尾部广告页数量。

    从最后一页往前扫描。ad_end 记录最后一个广告的位置（靠尾部的）。
    遇到广告 → 更新 ad_end，重置连续计数。
    连续 >= consecutive_ok 个非广告 → 已退出广告区，停止。
    """
    ad_end = len(pages)
    consecutive = 0
    for i in range(len(pages) - 1, -1, -1):
        if is_ad_image(pages[i]):
            ad_end = i
            consecutive = 0
        else:
            consecutive += 1
            if consecutive >= consecutive_ok:
                break
    return len(pages) - ad_end
