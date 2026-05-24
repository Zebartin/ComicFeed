"""项目日志模块：同时输出到控制台和数据库。"""
import logging
import sys
from datetime import datetime

_sqlite_handler = None

# 控制台 handler
_console = logging.StreamHandler(sys.stdout)
_console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"))


class DBLogHandler(logging.Handler):
    """将 WARNING 及以上日志写入数据库。"""

    def emit(self, record):
        try:
            from comicfeed.database import get_session
            from comicfeed.models import SystemLog
            import asyncio

            async def _write():
                async with get_session() as s:
                    s.add(SystemLog(
                        timestamp=datetime.utcnow(),
                        level=record.levelname,
                        source=record.name,
                        message=self.format(record),
                    ))
                    await s.commit()

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_write())
            except RuntimeError:
                pass
        except Exception:
            pass


def setup(level: int = logging.INFO):
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(_console)
    db = DBLogHandler()
    db.setLevel(logging.WARNING)
    db.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(db)


def get(name: str) -> logging.Logger:
    return logging.getLogger(name)
