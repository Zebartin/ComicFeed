"""下载队列追踪：pending → active → completed/failed。"""


class DownloadTracker:
    def __init__(self, keep_recent: int = 50):
        self._pending: list[dict] = []
        self._active: dict[str, dict] = {}
        self._completed: list[dict] = []
        self._failed: list[dict] = []
        self._keep = keep_recent

    def enqueue(self, gallery_id: str, title: str = "", total_pages: int = 0,
                cover_url: str = "", web_url: str = "", retry_kwargs: dict | None = None):
        task = {"gallery_id": gallery_id, "title": title, "total_pages": total_pages,
                "downloaded": 0, "cover_url": cover_url, "web_url": web_url,
                "status": "pending", "retry_kwargs": retry_kwargs or {}}
        self._pending.append(task)

    def started(self, gallery_id: str, title: str, total_pages: int,
                cover_url: str = "", web_url: str = ""):
        prev = None
        for i, t in enumerate(self._pending):
            if t["gallery_id"] == gallery_id:
                prev = self._pending.pop(i)
                break
        task = {"gallery_id": gallery_id, "title": title, "total_pages": total_pages,
                "downloaded": 0, "cover_url": cover_url, "web_url": web_url,
                "status": "active",
                "retry_kwargs": prev.get("retry_kwargs", {}) if prev else {}}
        self._active[gallery_id] = task

    def progress(self, gallery_id: str, downloaded: int):
        if gallery_id in self._active:
            self._active[gallery_id]["downloaded"] = downloaded

    def finished(self, gallery_id: str):
        task = self._active.pop(gallery_id, None)
        if task:
            task["status"] = "completed"
            self._completed.append(task)
            if len(self._completed) > self._keep:
                self._completed = self._completed[-self._keep:]

    def failed(self, gallery_id: str, error: str = "", title: str = "",
               total_pages: int = 0, cover_url: str = "", web_url: str = ""):
        task = self._active.pop(gallery_id, None)
        if task is None:
            pending_task = None
            keep = []
            for t in self._pending:
                if t["gallery_id"] == gallery_id:
                    pending_task = t
                else:
                    keep.append(t)
            self._pending = keep
            task = {"gallery_id": gallery_id, "status": "failed", "error": error,
                    "title": title, "total_pages": total_pages,
                    "cover_url": cover_url, "web_url": web_url, "downloaded": 0}
            if pending_task:
                task["retry_kwargs"] = pending_task.get("retry_kwargs", {})
        else:
            task["error"] = error
        task["status"] = "failed"
        self._failed.append(task)
        if len(self._failed) > self._keep:
            self._failed = self._failed[-self._keep:]

    def clear_completed(self):
        self._completed.clear()

    def clear_failed(self):
        self._failed.clear()

    def remove_failed(self, gallery_id: str):
        self._failed = [t for t in self._failed if t["gallery_id"] != gallery_id]

    def snapshot(self) -> dict:
        return {
            "pending": list(self._pending),
            "active": list(self._active.values()),
            "completed": list(self._completed),
            "failed": list(self._failed),
        }
