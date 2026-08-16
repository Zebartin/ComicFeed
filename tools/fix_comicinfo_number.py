"""修正已有 CBZ 的 ComicInfo.xml Number 字段。

按文件名排序，从 1 开始顺序编号。

用法: uv run python tools/fix_comicinfo_number.py <目录路径>
"""
import argparse
import os
import xml.etree.ElementTree as ET
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED


def fix_cbz(path: str, new_number: str) -> bool:
    """修改单个 CBZ 的 Number。返回是否修改。"""
    with open(path, "rb") as f:
        data = f.read()

    with ZipFile(BytesIO(data), "r") as z:
        if "ComicInfo.xml" not in z.namelist():
            return False
        xml_content = z.read("ComicInfo.xml")
        entries = {}
        for name in z.namelist():
            entries[name] = z.read(name)

    root = ET.fromstring(xml_content)
    number_el = root.find("Number")
    if number_el is None:
        # 无 Number 字段则创建
        number_el = ET.SubElement(root, "Number")

    old_number = number_el.text or ""
    if old_number == new_number:
        return False

    number_el.text = new_number
    xml_content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    entries["ComicInfo.xml"] = xml_content

    print(f"  Number: {old_number or '(空)'} → {new_number}")

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

    cbz_files = sorted(
        os.path.join(args.directory, fn)
        for fn in os.listdir(args.directory)
        if fn.lower().endswith(".cbz")
    )
    if not cbz_files:
        print("未找到 CBZ 文件")
        return

    fixed = 0
    for vol, path in enumerate(cbz_files, 1):
        if fix_cbz(path, str(vol)):
            fixed += 1

    print(f"\n修正 {fixed}/{len(cbz_files)} 个文件")


if __name__ == "__main__":
    main()
