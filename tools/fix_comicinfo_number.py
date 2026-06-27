"""修正已有 CBZ 的 ComicInfo.xml Number 字段为 {native_id}{vol:02d} 格式。

用法: uv run python tools/fix_comicinfo_number.py <目录路径>
"""
import argparse
import os
import re
import xml.etree.ElementTree as ET
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

# CBZ 文件名: [{native_id}] {title} ({start}-{end}).cbz 或 [{native_id}] {title}.cbz
_FILENAME_RE = re.compile(r"^\[(\d+)\].*?(?:\((\d+)-(\d+)\))?\.cbz$", re.IGNORECASE)
cbz_max_pages = None

def fix_cbz(path: str) -> bool:
    fname = os.path.basename(path)
    m = _FILENAME_RE.match(fname)
    if not m:
        print(f"  跳过: 文件名不匹配格式: {fname}")
        return False

    native_id = m.group(1)
    start_page = int(m.group(2)) if m.group(2) else None
    end_page = int(m.group(3)) if m.group(3) else None

    if start_page is None or end_page is None:
        print(f"  跳过：没有cbz分卷")
        return False
    
    global cbz_max_pages
    if cbz_max_pages is None:
        cbz_max_pages = end_page - start_page + 1
    vol = (start_page - 1) // cbz_max_pages + 1
    new_number = f"{vol}"
    
    # 读 ZIP
    with open(path, "rb") as f:
        data = f.read()

    with ZipFile(BytesIO(data), "r") as z:
        if "ComicInfo.xml" not in z.namelist():
            print(f"  跳过: 无 ComicInfo.xml")
            return False
        xml_content = z.read("ComicInfo.xml")
        # 读取所有 entry 数据
        entries = {}
        for name in z.namelist():
            entries[name] = z.read(name)

    # 解析并修正 Number
    root = ET.fromstring(xml_content)
    number_el = root.find("Number")
    if number_el is None:
        print(f"  跳过: ComicInfo.xml 无 Number 字段")
        return False

    # 如果 Number 已经符合格式就跳过
    old_number = number_el.text or ""
    if old_number == new_number:
        print(f"  跳过: Number 已符合格式 ({old_number})")
        return False

    number_el.text = new_number
    xml_content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    entries["ComicInfo.xml"] = xml_content

    print(f"  Number: {old_number} → {new_number}")

    # 写回
    buf = BytesIO()
    with ZipFile(buf, "w", ZIP_DEFLATED) as z:
        for name, content in entries.items():
            if name.endswith("/"):
                continue
            z.writestr(name, content)
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    return True


def main():
    parser = argparse.ArgumentParser(description="修正 CBZ 的 ComicInfo Number 字段")
    parser.add_argument("directory", help="CBZ 文件所在目录")
    args = parser.parse_args()

    cbz_files = [
        os.path.join(args.directory, fn)
        for fn in os.listdir(args.directory)
        if fn.lower().endswith(".cbz")
    ]
    if not cbz_files:
        print("未找到 CBZ 文件")
        return

    fixed = 0
    for path in sorted(cbz_files):
        print(os.path.basename(path))
        if fix_cbz(path):
            fixed += 1

    print(f"\n修正 {fixed}/{len(cbz_files)} 个文件")


if __name__ == "__main__":
    main()
