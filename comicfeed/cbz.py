import re
import xml.etree.ElementTree as ET
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from comicfeed.sources.base import GalleryDetail

# 头部事件标记: (C97), (COMIC1), (C100), etc.
_HEAD_PAREN = re.compile(r"^(\([^\(\)]+\)\s*)+")

# 尾部括号标签: [...]、(...)、【...】等
_BRACKET = r"[\[\(（【［](?:[^\[\]\(\){}【】（）［］]+)[\]\)}】）］]"
_TAIL_BRACKETS = re.compile(rf"(?:\s*{_BRACKET})+$")
_SINGLE_BRACKET = re.compile(_BRACKET)

# 格式/版本标签黑名单（这些应该从标题中去除）
_BLACKLIST = re.compile(
    r"汉化|漢化|个汉|個漢|翻译|翻譯|翻訳|機翻|机翻"
    r"|Digital|DL版|Chinese|中文|中国語|English"
    r"|censor|修正|Decensored|Uncensored|Colorized"
    r"|全彩|无修正|中国翻訳"
    r"|AI Generated|AI生成"
    r"|COMIC.*\d+",
    re.IGNORECASE,
)


def normalize_title(title: str) -> str:
    """去除事件标记和尾部格式标签，归一化空格。"""
    t = _HEAD_PAREN.sub("", title.strip())

    def _filter_tail(m: re.Match) -> str:
        brackets = _SINGLE_BRACKET.findall(m.group())
        # 保留不在黑名单中的括号内容
        keep = [b for b in brackets if not _BLACKLIST.search(b)]
        result = " ".join(b.strip() for b in keep)
        if result and m.group().startswith(" "):
            result = " " + result
        return result

    t = _TAIL_BRACKETS.sub(_filter_tail, t)
    return re.sub(r"\s+", " ", t).strip()


# Windows 文件名非法字符 → 全角版本
_FILENAME_MAP = str.maketrans({
    '<': '＜', '>': '＞', ':': '：', '"': '＂',
    '/': '／', '\\': '＼', '|': '｜', '?': '？', '*': '＊',
})


def sanitize_filename(name: str) -> str:
    return name.translate(_FILENAME_MAP)


def make_cbz_name(native_id: str, normalized_title: str, start_page: int, end_page: int, total_pages: int = 0) -> str:
    """生成 CBZ 文件名: [id] title (0001-0034).cbz"""
    name = f"[{native_id}] {normalized_title}"
    if total_pages > 0 and start_page == 1 and end_page >= total_pages:
        pass  # 不分卷，不加页码范围
    else:
        name += f" ({start_page:04d}-{end_page:04d})"
    name = sanitize_filename(name)
    return f"{name}.cbz"


def read_cbz_pages(path: str) -> list[bytes]:
    """读取 CBZ 文件中的所有页面（按文件名排序）。"""
    import zipfile
    pages = []
    with zipfile.ZipFile(path, "r") as z:
        for name in sorted(z.namelist()):
            if not name.endswith("/") and not name.lower().endswith(".xml"):
                pages.append(z.read(name))
    return pages


def _build_comicinfo(detail: GalleryDetail) -> bytes:
    root = ET.Element("ComicInfo")
    ET.SubElement(root, "Title").text = detail.title
    ET.SubElement(root, "Number").text = detail.native_id
    ET.SubElement(root, "Tags").text = ", ".join(detail.tags)
    if detail.upload_date:
        try:
            from datetime import datetime
            if detail.upload_date.isdigit():
                dt = datetime.fromtimestamp(int(detail.upload_date))
            else:
                dt = datetime.fromisoformat(detail.upload_date)
            ET.SubElement(root, "Year").text = str(dt.year)
            ET.SubElement(root, "Month").text = str(dt.month)
            ET.SubElement(root, "Day").text = str(dt.day)
        except (ValueError, OSError):
            pass
    if detail.web_url:
        ET.SubElement(root, "Web").text = detail.web_url
    tree = ET.ElementTree(root)
    buf = BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()


def pack_cbz(output: BytesIO, name: str, detail: GalleryDetail, pages: list[bytes], start_page: int = 1):
    """打包 CBZ 文件到 output，页码从 start_page 开始编号。"""
    with ZipFile(output, "w", ZIP_DEFLATED) as z:
        for i, data in enumerate(pages, start_page):
            z.writestr(f"{i:04d}.jpg", data)
        z.writestr("ComicInfo.xml", _build_comicinfo(detail))
