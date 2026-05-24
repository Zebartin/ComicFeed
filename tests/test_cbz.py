from io import BytesIO
from zipfile import ZipFile

from comicfeed.cbz import make_cbz_name, normalize_title, pack_cbz
from comicfeed.sources.base import GalleryDetail


def test_normalize_title_removes_event_and_format_tags():
    """去除事件标记和格式标签。"""
    assert normalize_title("(C97) [AERODOG (inu)] Title [Digital]") == \
        "[AERODOG (inu)] Title"
    assert normalize_title("(C100) [Circle] Comic Name [English] [Decensored]") == \
        "[Circle] Comic Name"
    assert normalize_title("(COMIC1) Work [Chinese]") == "Work"


def test_normalize_title_keeps_artist_brackets():
    """保留画师/社团的括号。"""
    assert normalize_title("[AERODOG (inu)] 先生!射精の時間ですよ") == \
        "[AERODOG (inu)] 先生!射精の時間ですよ"
    assert normalize_title("[Circle (Name)] My Comic") == \
        "[Circle (Name)] My Comic"


def test_normalize_title_no_tags():
    """没有多余标签的标题原样返回。"""
    assert normalize_title("Just a Comic Title") == "Just a Comic Title"
    assert normalize_title("  spaces  already  ") == "spaces already"


def test_normalize_title_removes_chinese_format_tags():
    """去除中文格式标签（汉化、翻译、修正等）。"""
    assert normalize_title("[Circle] Title [汉化]") == "[Circle] Title"
    assert normalize_title("Title [中国翻訳] [无修正]") == "Title"
    assert normalize_title("Title [DL版] [机翻]") == "Title"


def test_normalize_title_mixed_bracket_types():
    """处理混合括号类型（圆括号、方括号、中文括号等）。"""
    assert normalize_title("[Author] Title （Digital）") == "[Author] Title"
    assert normalize_title("Title【中国翻訳】") == "Title"


def test_make_cbz_name_single_volume():
    """单卷 CBZ 文件名。"""
    name = make_cbz_name("455819", "Sample Comic Title", 1, 34)
    assert name == "[455819] Sample Comic Title (0001-0034).cbz"


def test_make_cbz_name_no_split_omits_range():
    """不分卷时文件名不加页码范围。"""
    name = make_cbz_name("455819", "Comic", 1, 42, total_pages=42)
    assert name == "[455819] Comic.cbz"


def test_make_cbz_name_multi_volume():
    """多卷 CBZ 文件名。"""
    name = make_cbz_name("455819", "Sample Comic Title", 61, 90)
    assert name == "[455819] Sample Comic Title (0061-0090).cbz"


def test_sanitize_filename():
    """替换非法字符为全角。"""
    from comicfeed.cbz import sanitize_filename
    assert sanitize_filename("a|b") == "a｜b"
    assert sanitize_filename("a:b") == "a：b"
    assert sanitize_filename("a<b>c") == "a＜b＞c"


def test_pack_cbz_creates_valid_zip_with_comicinfo():
    """pack_cbz 创建包含页面图片和 ComicInfo.xml 的有效 zip。"""
    detail = GalleryDetail(
        native_id="455819",
        title="Sample Comic",
        cover_url="https://t.nhentai.net/galleries/12345/cover.jpg",
        page_urls=[],
        tags=["full color", "big breasts"],
        reported_pages=2,
    )
    pages = [b"\xff\xd8\xff" + b"\x00" * 100, b"\xff\xd8\xff" + b"\x00" * 200]
    name = make_cbz_name("455819", "Sample Comic", 1, 2)
    output = BytesIO()
    pack_cbz(output, name, detail, pages)

    output.seek(0)
    with ZipFile(output) as z:
        names = z.namelist()
        assert "ComicInfo.xml" in names
        assert "0001.jpg" in names
        assert "0002.jpg" in names
        # 验证 ComicInfo.xml 包含标签
        xml = z.read("ComicInfo.xml").decode("utf-8")
        assert "Sample Comic" in xml
        assert "455819" in xml
        assert "full color" in xml


def test_pack_cbz_respects_start_page():
    """start_page 参数控制内部页码偏移。"""
    detail = GalleryDetail(
        native_id="455819",
        title="Test",
        cover_url="",
        tags=[],
        reported_pages=2,
    )
    pages = [b"\xff\xd8\xff" + b"\x00" * 10, b"\xff\xd8\xff" + b"\x00" * 10]
    output = BytesIO()
    pack_cbz(output, "test.cbz", detail, pages, start_page=31)

    output.seek(0)
    with ZipFile(output) as z:
        names = sorted(z.namelist())
        assert "0031.jpg" in names
        assert "0032.jpg" in names
