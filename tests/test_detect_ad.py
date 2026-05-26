"""广告页检测测试"""
import io
from PIL import Image

from comicfeed.detect_ad import detect_ads_from_tail, is_ad_image


def _make_img(width, height, color=True):
    """生成测试用图片。"""
    img = Image.new("RGB" if color else "L", (width, height), (128, 100, 80) if color else 128)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_normal_page_not_ad():
    """正常漫画页（大尺寸、接近 A4 比例）不算广告。"""
    data = _make_img(1280, 1800)
    assert not is_ad_image(data)


def test_banner_ad_detected():
    """横幅广告（宽高比异常）被识别。"""
    # 728x90 是典型横幅广告
    data = _make_img(728, 90)
    assert is_ad_image(data)


def test_tiny_image_is_ad():
    """极小图片（<100px 任意边）算广告。"""
    data = _make_img(80, 120)
    assert is_ad_image(data)


def test_grayscale_not_ad():
    """灰度图不算广告（参考 ComicReadScript 逻辑）。"""
    data = _make_img(800, 600, color=False)
    assert not is_ad_image(data)


def test_detect_ads_from_tail():
    """从尾部扫描，连续 3 张非广告则停，之前的都算广告。"""
    # 模拟 8 页：前 5 页正常，后 3 页广告
    pages = [
        _make_img(1280, 1800),  # 0: 正常
        _make_img(1280, 1800),  # 1: 正常
        _make_img(1280, 1800),  # 2: 正常
        _make_img(1280, 1800),  # 3: 正常
        _make_img(1280, 1800),  # 4: 正常
        _make_img(728, 90),     # 5: 横幅广告
        _make_img(728, 90),     # 6: 横幅广告
        _make_img(728, 90),     # 7: 横幅广告
    ]
    # 从后往前：7(ad), 6(ad), 5(ad), 4(ok), 3(ok), 2(ok) → 连续 3 ok → 停
    # 5,6,7 是广告 → 实际有效页数 = 5
    ad_count = detect_ads_from_tail(pages, consecutive_ok=3)
    assert ad_count == 3  # 尾部 3 页是广告


def test_no_ads_all_normal():
    """没有广告的图集返回 0。"""
    pages = [_make_img(1280, 1800) for _ in range(5)]
    assert detect_ads_from_tail(pages) == 0
