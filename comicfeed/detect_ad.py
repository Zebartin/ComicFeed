"""广告页检测：从尾部扫描，连续 N 张非广告则停。"""
from io import BytesIO

from PIL import Image


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

    从最后一页往前扫描，如果连续 consecutive_ok 张都不是广告，停止扫描。
    扫描过的页中，所有被判定为广告的页计入尾部广告。
    """
    ad_count = 0
    ok_streak = 0
    for i in range(len(pages) - 1, -1, -1):
        if is_ad_image(pages[i]):
            ad_count += 1
            ok_streak = 0
        else:
            ok_streak += 1
            # 不是广告的页也计入扫描范围（它们可能是"不小心被扫到的正常页"）
            # 但一旦 OK 连续达标，就停止
        if ok_streak >= consecutive_ok:
            break
    return ad_count
