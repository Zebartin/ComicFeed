"""ComicFeed 启动入口。

用法:
    uv run python main.py              # 启动 Web 服务
    uv run python main.py --host 0.0.0.0 --port 8080
"""
import argparse
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from comicfeed.database import create_tables, init_db
from comicfeed.source_manager import SourceManager
from comicfeed.web.app import create_app


def main():
    parser = argparse.ArgumentParser(description="ComicFeed")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default="comicfeed.db")
    parser.add_argument("--auth-user", default="admin")
    parser.add_argument("--auth-pass", default="")
    parser.add_argument("--debug", action="store_true", help="输出 DEBUG 级别日志")
    args = parser.parse_args()

    import logging
    from comicfeed.log import setup
    init_db(args.db)
    setup(level=logging.DEBUG if args.debug else logging.INFO,
          db_path=args.db if args.db != ":memory:" else None)
    asyncio.run(create_tables())

    from comicfeed.config import get_setting, set_setting
    from comicfeed.credentials import init as cred_init
    key = asyncio.run(get_setting("_fernet_key", ""))
    if not key:
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode("utf-8")
        asyncio.run(set_setting("_fernet_key", key))
    cred_init(key)

    from comicfeed.log import get

    source_mgr = SourceManager()
    try:
        import os as _os
        sources_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "comicfeed", "sources")
        keys = source_mgr.load_sources(sources_dir)
        get("main").info("已加载源: %s", ', '.join(keys) if keys else '(无)')
    except Exception as e:
        get("main").error("源加载失败: %s", e)

    from comicfeed.komga import register_komga_hook
    register_komga_hook()

    from comicfeed.notifications import register_email_hook
    register_email_hook()

    from comicfeed.tag_translator import get_translator
    asyncio.run(get_translator().load())

    from comicfeed.downloader import DownloadPool
    download_pool = DownloadPool(max_workers=5)

    config = {"auth_username": args.auth_user, "auth_password": args.auth_pass}
    app = create_app(config, source_manager=source_mgr, download_pool=download_pool)

    print(f"ComicFeed 启动: http://{args.host}:{args.port}")
    print(f"  定时检查: 每 10 分钟 (按订阅间隔执行)")

    get("main").info("ComicFeed 启动完成")
    if args.auth_pass:
        print(f"  用户名: {args.auth_user}")

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
