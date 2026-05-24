import json

from comicfeed.tag_translator import TagTranslator

_SAMPLE_DB = json.dumps({
    "namespaces": {
        "female": "女性",
        "male": "男性",
        "artist": "画师",
        "group": "团队",
        "parody": "原作",
        "character": "角色",
    },
    "tags": {
        "full color": "全彩",
        "big breasts": "巨乳",
        "sole male": "单男主",
        "schoolgirl uniform": "女生制服",
    },
})


def test_translate_known_tag():
    """已知标签翻译为中文。"""
    tt = TagTranslator(db_data=_SAMPLE_DB)
    assert tt.translate("full color") == "全彩"
    assert tt.translate("big breasts") == "巨乳"


def test_translate_unknown_tag_returns_original():
    """未知标签返回原文。"""
    tt = TagTranslator(db_data=_SAMPLE_DB)
    assert tt.translate("nonexistent tag") == "nonexistent tag"


def test_translate_with_namespace():
    """带命名空间的标签格式化输出。"""
    tt = TagTranslator(db_data=_SAMPLE_DB)
    result = tt.translate_tag("artist", "full color")
    assert "画师" in result
    assert "全彩" in result
