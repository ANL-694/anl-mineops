import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import router
from .config import get_settings
from .service import MineOpsService
from .storage import Store


def create_app(database: str | None = None) -> FastAPI:
    settings = get_settings()
    store = Store(database or settings.database)
    service = MineOpsService(store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        store.close()

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.state.service = service

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        code = exc.detail if isinstance(exc.detail, str) else "http_error"
        message = exc.detail if isinstance(exc.detail, str) else "请求失败"
        return JSONResponse(
            status_code=exc.status_code,
            content={"data": None, "meta": {}, "error": {"code": code, "message": message, "details": []}},
        )

    @app.middleware("http")
    async def bearer_guard(request: Request, call_next):
        if request.url.path.startswith("/api/v1"):
            client_host = request.client.host if request.client else ""
            local_hosts = {"127.0.0.1", "::1", "localhost", "testclient", "::ffff:127.0.0.1"}
            if client_host not in local_hosts:
                authorization = request.headers.get("authorization", "")
                expected = f"Bearer {settings.auth_token}" if settings.auth_token else ""
                if not expected or not secrets.compare_digest(authorization, expected):
                    return JSONResponse(
                        status_code=401,
                        content={
                            "data": None,
                            "meta": {},
                            "error": {
                                "code": "authentication_required",
                                "message": "非本机访问需要 Bearer token",
                                "details": [],
                            },
                        },
                        headers={"WWW-Authenticate": "Bearer"},
                    )
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(router)
    return app


app = create_app()
