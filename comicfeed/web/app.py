import base64
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from contextlib import asynccontextmanager

from comicfeed.services.download import DownloadPool
from comicfeed.services.queue import DownloadTracker
from comicfeed.infrastructure.source_manager import SourceManager
from comicfeed.web.routes.credentials import router as cred_router
from comicfeed.web.routes.galleries import router as gallery_router
from comicfeed.web.routes.logs import router as log_router
from comicfeed.web.routes.queue import router as queue_router
from comicfeed.web.routes.search import router as search_router
from comicfeed.web.routes.settings import router as settings_router
from comicfeed.web.routes.setup import router as setup_router
from comicfeed.web.routes.source_config import router as sc_router
from comicfeed.web.routes.sources import router as src_router
from comicfeed.web.routes.subscriptions import router as sub_router

_source_manager: SourceManager | None = None
_download_tracker: DownloadTracker | None = None


def get_source_manager() -> SourceManager | None:
    return _source_manager


def get_download_tracker() -> DownloadTracker | None:
    return _download_tracker


class BasicAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, username: str, password: str, exclude_paths: list[str] | None = None):
        super().__init__(app)
        self._username = username
        self._password = password
        self._exclude = exclude_paths or []

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._exclude:
            return await call_next(request)

        auth = request.headers.get("Authorization")
        if not auth or not auth.startswith("Basic "):
            return JSONResponse(
                {"detail": "Unauthorized"}, status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="ComicFeed"'},
            )

        credentials = auth.removeprefix("Basic ")
        try:
            decoded = base64.b64decode(credentials).decode("utf-8")
            username, _, password = decoded.partition(":")
        except Exception:
            return JSONResponse(
                {"detail": "Invalid credentials"}, status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="ComicFeed"'},
            )

        if not secrets.compare_digest(username, self._username):
            return JSONResponse(
                {"detail": "Unauthorized"}, status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="ComicFeed"'},
            )
        if not secrets.compare_digest(password, self._password):
            return JSONResponse(
                {"detail": "Unauthorized"}, status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="ComicFeed"'},
            )

        return await call_next(request)


def create_app(config: dict | None = None, source_manager: SourceManager | None = None,
               download_tracker: DownloadTracker | None = None, download_pool: DownloadPool | None = None) -> FastAPI:
    global _source_manager, _download_tracker
    _source_manager = source_manager or SourceManager()
    _download_tracker = download_tracker or DownloadTracker()
    download_pool = download_pool or DownloadPool()

    from fastapi.staticfiles import StaticFiles
    app = FastAPI()
    app.mount("/static", StaticFiles(directory="comicfeed/web/static"), name="static")

    # 认证：优先 DB，其次 config 字典（测试兼容），最后默认值
    import asyncio as _asyncio
    from comicfeed.infrastructure.config import get_setting as _gs
    if config:
        u = config.get("auth_username", "") or "admin"
        p = config.get("auth_password", "")
    else:
        u = _asyncio.run(_gs("auth_username")) or "admin"
        p = _asyncio.run(_gs("auth_password")) or ""
    if u and p:
        app.add_middleware(BasicAuthMiddleware, username=u, password=p, exclude_paths=["/health"])

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from comicfeed.infrastructure.scheduler import create_scheduler
        from comicfeed.infrastructure.config import get_setting
        interval = int(await get_setting("check_interval") or "10")
        scheduler = create_scheduler(_source_manager, download_pool, interval_minutes=interval)
        scheduler.start()
        yield
        scheduler.shutdown()

    app.router.lifespan_context = lifespan

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.include_router(sub_router)
    app.include_router(sc_router)
    app.include_router(src_router)
    app.include_router(gallery_router)
    app.include_router(cred_router)
    app.include_router(log_router)
    app.include_router(queue_router)
    app.include_router(settings_router)
    app.include_router(search_router)
    app.include_router(setup_router)

    templates = Jinja2Templates(directory="comicfeed/web/templates")

    @app.get("/", response_class=HTMLResponse)
    async def page_index(request: Request):
        return templates.TemplateResponse(request, "subscriptions.html")

    @app.get("/sources", response_class=HTMLResponse)
    async def page_sources(request: Request):
        return templates.TemplateResponse(request, "sources.html")

    @app.get("/galleries", response_class=HTMLResponse)
    async def page_galleries(request: Request):
        return templates.TemplateResponse(request, "galleries.html")

    @app.get("/settings", response_class=HTMLResponse)
    async def page_settings(request: Request):
        return templates.TemplateResponse(request, "settings.html")

    @app.get("/queue", response_class=HTMLResponse)
    async def page_queue(request: Request):
        return templates.TemplateResponse(request, "queue.html")

    @app.get("/search", response_class=HTMLResponse)
    async def page_search(request: Request):
        return templates.TemplateResponse(request, "search.html")

    @app.get("/setup", response_class=HTMLResponse)
    async def page_setup(request: Request):
        return templates.TemplateResponse(request, "setup.html")

    @app.get("/logs", response_class=HTMLResponse)
    async def page_logs(request: Request):
        return templates.TemplateResponse(request, "logs.html")

    return app
