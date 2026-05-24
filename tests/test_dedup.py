from comicfeed.dedup import find_similar_groups

# 模拟搜索返回的摘要
_Summary = lambda nid, title, pages: type("s", (), {"native_id": nid, "title": title, "page_count": pages, "cover_url": ""})()


def test_identical_titles_grouped():
    """相同标题归入同一候选组。"""
    items = [
        _Summary("1", "Sample Comic Title", 32),
        _Summary("2", "Sample Comic Title", 32),
    ]
    groups = find_similar_groups(items)
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_similar_titles_grouped():
    """标题相似但格式不同的归入同一候选组。"""
    items = [
        _Summary("1", "(C97) [Circle] Comic Name [Digital]", 32),
        _Summary("2", "[Circle] Comic Name [English]", 30),
    ]
    groups = find_similar_groups(items)
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_different_titles_separated():
    """不同的标题保持分开。"""
    items = [
        _Summary("1", "My Comic Adventure", 20),
        _Summary("2", "Something Else Entirely", 20),
        _Summary("3", "Totally Different Story", 20),
    ]
    groups = find_similar_groups(items)
    assert groups == []  # 没有相似组，全部都是单独的


def test_mixed_groups():
    """混合场景：相似和不同的正确分组。"""
    items = [
        _Summary("1", "My Comic [Digital]", 30),
        _Summary("2", "My Comic [English]", 32),
        _Summary("3", "Other Comic", 20),
    ]
    groups = find_similar_groups(items)
    assert len(groups) == 1
    assert len(groups[0]) == 2
