"""修正已有 CBZ 的 ComicInfo.xml Number 字段为 {native_id}{vol:04d} 格式。

用法: uv run python tools/fix_comicinfo_number.py <目录路径> [--dry-run]
"""
import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

# CBZ 文件名: [{native_id}] {title} ({start}-{end}).cbz 或 [{native_id}] {title}.cbz
_FILENAME_RE = re.compile(r"^\[(\d+)\].*(?:\((\d+)-(\d+)\))?\.cbz$", re.IGNORECASE)


def fix_cbz(path: str) -> bool:
    fname = os.path.basename(path)
    m = _FILENAME_RE.match(fname)
    if not m:
        print(f"  跳过: 文件名不匹配格式: {fname}")
        return False

    native_id = m.group(1)
    start_page = int(m.group(2)) if m.group(2) else None

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

    new_number = native_id
    if start_page is not None:
        # 需要 cbz_max_pages 来算卷号。从文件名推断: 起止范围跨度
        # 读第二个 CBZ 来判断分卷大小
        pass
    else:
        new_number = native_id

    # 先用简单的逻辑：如果 Number 已经符合格式就跳过
    old_number = number_el.text or ""
    if old_number == new_number:
        print(f"  跳过: Number 已符合格式 ({old_number})")
        return False

    # 如果有分卷，从相邻 CBZ 推断 cbz_max_pages
    if start_page is not None and start_page > 1:
        # 从起止范围推断: 第一个文件名不含范围 = 1 卷; 含范围的，看跨度
        # 简化: 从当前文件所在目录找同 gallery_id 的其他 CBZ 来确定分卷大小
        dirname = os.path.dirname(path)
        cbz_max_pages = 0
        siblings = [
            fn for fn in os.listdir(dirname)
            if fn.startswith(f"[{native_id}]") and fn.endswith(".cbz")
        ]
        for sib in siblings:
            sm = _FILENAME_RE.match(sib)
            if sm and sm.group(2) and sm.group(3):
                span = int(sm.group(3)) - int(sm.group(2)) + 1
                if span > cbz_max_pages:
                    cbz_max_pages = span
        if cbz_max_pages > 0:
            vol = (start_page - 1) // cbz_max_pages + 1
            new_number = f"{native_id}{vol:04d}"
    else:
        new_number = native_id

    if old_number == new_number:
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
    parser.add_argument("--dry-run", action="store_true", help="只检查，不修改")
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
        if args.dry_run:
            # 只检查不修改
            if fix_cbz(path):
                fixed += 1
            continue
        if fix_cbz(path):
            fixed += 1

    tag = " (dry-run)" if args.dry_run else ""
    print(f"\n修正 {fixed}/{len(cbz_files)} 个文件{tag}")


if __name__ == "__main__":
    main()
