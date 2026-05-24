"""项目日志模块：同时输出到控制台和数据库。"""
import logging
import sqlite3
import sys
import threading
from datetime import datetime

_db_path: str | None = None

_console = logging.StreamHandler(sys.stdout)
_console.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"
))


class DBLogHandler(logging.Handler):
    """将 WARNING 及以上日志写入数据库（独立连接，避免事件循环问题）。"""

    def emit(self, record):
        if _db_path is None:
            return
        try:
            conn = sqlite3.connect(_db_path)
            conn.execute(
                "INSERT INTO system_log (timestamp, level, source, message) VALUES (?, ?, ?, ?)",
                (datetime.now().isoformat(), record.levelname, record.name, self.format(record)),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass


def setup(level: int = logging.INFO, db_path: str | None = None):
    global _db_path
    _db_path = db_path

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(_console)

    if db_path:
        db = DBLogHandler()
        db.setLevel(logging.WARNING)
        db.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(db)


def get(name: str) -> logging.Logger:
    return logging.getLogger(name)
