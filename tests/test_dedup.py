from comicfeed.services.dedup import find_similar_groups, resolve_duplicates

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
    assert groups == []


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


# --- 阶段 2：页数比对 ---


def test_resolve_duplicates_page_diff_within_threshold():
    """页数差异 ≤15%，保留页数多的。"""
    keep = resolve_duplicates([("a", 32), ("b", 30)])
    assert keep == {"a"}


def test_resolve_duplicates_page_diff_exceeds_threshold():
    """页数差异 >15%，都保留。"""
    keep = resolve_duplicates([("a", 32), ("b", 20)])
    assert keep == {"a", "b"}


def test_resolve_duplicates_same_pages_keep_newer_id():
    """页数相同，保留 ID 较大的。"""
    keep = resolve_duplicates([("100", 30), ("200", 30)])
    assert keep == {"200"}


def test_resolve_duplicates_three_candidates():
    """多个候选中正确筛选。"""
    keep = resolve_duplicates([("a", 30), ("b", 28), ("c", 20)])
    assert keep == {"a", "c"}
