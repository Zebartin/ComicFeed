import base64
import secrets

from fastapi import FastAPI, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


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
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        credentials = auth.removeprefix("Basic ")
        try:
            decoded = base64.b64decode(credentials).decode("utf-8")
            username, _, password = decoded.partition(":")
        except Exception:
            return JSONResponse({"detail": "Invalid credentials"}, status_code=401)

        if not secrets.compare_digest(username, self._username):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        if not secrets.compare_digest(password, self._password):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        return await call_next(request)


def create_app(config: dict | None = None) -> FastAPI:
    if config is None:
        config = {}
    app = FastAPI()

    auth_user = config.get("auth_username", "")
    auth_pass = config.get("auth_password", "")
    if auth_user and auth_pass:
        app.add_middleware(BasicAuthMiddleware, username=auth_user, password=auth_pass, exclude_paths=["/health"])

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/subscriptions")
    async def list_subscriptions():
        return []

    return app
