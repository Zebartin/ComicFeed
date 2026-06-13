import json

from comicfeed.infrastructure.tag_translator import TagTranslator

_SAMPLE_DB = {
    "namespaces": {"artist": "画师", "group": "团队", "tag": "标签"},
    "tags": {
        "artist": {"inu": "犬"},
        "tag": {"full color": "全彩", "big breasts": "巨乳", "sole female": "独自女性"},
    },
}


def _make_tt() -> TagTranslator:
    """创建一个用内存数据的翻译器。"""
    tt = TagTranslator.__new__(TagTranslator)
    tt._db_path = ""
    tt._namespaces = _SAMPLE_DB["namespaces"]
    tt._tags = _SAMPLE_DB["tags"]
    return tt


def test_translate_known_tag():
    """已知标签翻译为中文，普通 namespace 省略前缀。"""
    tt = _make_tt()
    assert tt.translate("tag", "full color") == "全彩"
    assert tt.translate("tag", "big breasts") == "巨乳"


def test_artist_namespace_keeps_prefix():
    """画师等关键 namespace 保留前缀。"""
    tt = _make_tt()
    assert tt.translate("artist", "inu") == "画师：犬"


def test_translate_unknown_tag_returns_original():
    """未知标签返回原文。"""
    tt = _make_tt()
    result = tt.translate("tag", "nonexistent")
    assert "nonexistent" in result


def test_translate_with_namespace():
    """命名空间也会翻译，关键 namespace 保留前缀。"""
    tt = _make_tt()
    result = tt.translate("artist", "inu")
    assert result == "画师：犬"


def test_translate_no_namespace_searches_all():
    """无 namespace 时全库搜索。"""
    tt = _make_tt()
    result = tt.translate("", "full color")
    assert "全彩" in result


def test_translate_no_namespace_not_found():
    """无 namespace 且找不到时返回原文。"""
    tt = _make_tt()
    result = tt.translate("", "nonexistent tag")
    assert result == "nonexistent tag"


def test_translate_composite_tag_first_part():
    """复合标签：整体不存在时查找第一部分。"""
    tt = _make_tt()
    result = tt.translate("tag", "sole female|sole male")
    assert result == "独自女性"


def test_translate_composite_tag_second_part():
    """复合标签：第一部分不存在时查找第二部分。"""
    tt = _make_tt()
    result = tt.translate("tag", "unknown|big breasts")
    assert result == "巨乳"


def test_translate_composite_tag_strips_spaces():
    """复合标签各部分 strip 空格。"""
    tt = _make_tt()
    result = tt.translate("tag", "sole female | big breasts")
    assert result == "独自女性"


def test_find_namespaces_composite():
    """find_namespaces 也支持拆分查找。"""
    tt = _make_tt()
    # "sole female|unknown" → 找到 "sole female" 的 namespace
    result = tt.find_namespaces("sole female|unknown")
    assert "tag" in result
