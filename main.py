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
    args = parser.parse_args()

    init_db(args.db)
    asyncio.run(create_tables())

    source_mgr = SourceManager()
    try:
        source_mgr.load_sources("comicfeed/sources")
    except Exception:
        pass

    config = {"auth_username": args.auth_user, "auth_password": args.auth_pass}
    app = create_app(config, source_manager=source_mgr)

    print(f"ComicFeed 启动: http://{args.host}:{args.port}")
    if args.auth_pass:
        print(f"  用户名: {args.auth_user}")

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
