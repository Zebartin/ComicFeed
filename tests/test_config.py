from comicfeed.infrastructure.database import create_tables, init_db
from comicfeed.infrastructure.config import get_setting, set_setting


async def test_get_and_set_setting():
    """全局设置可以写入和读取。"""
    init_db(":memory:")
    await create_tables()

    await set_setting("download_path", "/data/comics")
    await set_setting("global_concurrency", "8")

    assert await get_setting("download_path") == "/data/comics"
    assert await get_setting("global_concurrency") == "8"
    assert await get_setting("nonexistent", "fallback") == "fallback"
