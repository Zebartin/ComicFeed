from comicfeed.services.queue import DownloadTracker


def test_tracker_start_and_finish():
    tracker = DownloadTracker()
    s = tracker.snapshot()
    assert s["pending"] == [] and s["active"] == [] and s["completed"] == []

    tracker.started("nhentai:123", "Test Comic", 30)
    assert len(tracker.snapshot()["active"]) == 1
    a = tracker.snapshot()["active"][0]
    assert a["gallery_id"] == "nhentai:123"
    assert a["title"] == "Test Comic"
    assert a["total_pages"] == 30
    assert a["downloaded"] == 0

    tracker.progress("nhentai:123", 15)
    assert tracker.snapshot()["active"][0]["downloaded"] == 15

    tracker.finished("nhentai:123")
    assert tracker.snapshot()["active"] == []
    assert len(tracker.snapshot()["completed"]) == 1
    assert tracker.snapshot()["completed"][0]["gallery_id"] == "nhentai:123"


def test_tracker_enqueue_flow():
    tracker = DownloadTracker()
    tracker.enqueue("a", "Title A", 10, cover_url="http://x/a.jpg")
    tracker.enqueue("b", "Title B", 20)
    s = tracker.snapshot()
    assert len(s["pending"]) == 2
    assert s["pending"][0]["status"] == "pending"

    tracker.started("a", "Title A", 10, cover_url="http://x/a.jpg")
    s = tracker.snapshot()
    assert len(s["pending"]) == 1
    assert len(s["active"]) == 1
    assert s["active"][0]["gallery_id"] == "a"

    tracker.finished("a")
    tracker.failed("b", "some error")
    s = tracker.snapshot()
    assert s["pending"] == [] and s["active"] == []
    assert len(s["completed"]) == 1
    assert len(s["failed"]) == 1
    assert s["failed"][0]["error"] == "some error"
