from comicfeed.downloader import DownloadTracker


def test_tracker_starts_and_finishes():
    """tracker 记录开始和完成状态。"""
    tracker = DownloadTracker()
    assert len(tracker.active()) == 0

    tracker.started("nhentai:123", "Test Comic", 30)
    active = tracker.active()
    assert len(active) == 1
    assert active[0]["gallery_id"] == "nhentai:123"
    assert active[0]["title"] == "Test Comic"
    assert active[0]["total_pages"] == 30
    assert active[0]["downloaded"] == 0

    tracker.progress("nhentai:123", 15)
    assert tracker.active()[0]["downloaded"] == 15

    tracker.finished("nhentai:123")
    assert len(tracker.active()) == 0


def test_tracker_multiple_downloads():
    """同时追踪多个下载任务。"""
    tracker = DownloadTracker()
    tracker.started("a", "A", 10)
    tracker.started("b", "B", 20)
    assert len(tracker.active()) == 2

    tracker.finished("a")
    assert len(tracker.active()) == 1
    assert tracker.active()[0]["gallery_id"] == "b"
