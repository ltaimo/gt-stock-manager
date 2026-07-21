from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.database import Base, engine
from app.errors import http_error_handler, unexpected_error_handler, validation_error_handler
from app.maintenance.migrate_schema import ensure_schema
from app.routers import about, audit, auth, dashboard, documents, hse, imports, internal_ops, movements, notifications, preferences, procurement, products, profiles, reports, requisitions, settings as settings_router, sync, users
from app.services.sync import push_snapshot_to_target


settings = get_settings()
Base.metadata.create_all(bind=engine)
ensure_schema()

app = FastAPI(title=settings.app_name)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(HTTPException, http_error_handler)
app.add_exception_handler(StarletteHTTPException, http_error_handler)
app.add_exception_handler(Exception, unexpected_error_handler)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax", https_only=settings.secure_cookies)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


async def _sync_mirror_loop():
    import asyncio

    await asyncio.sleep(15)
    while True:
        try:
            await asyncio.to_thread(push_snapshot_to_target, settings.sync_target_url, settings.sync_token)
        except Exception as exc:
            print(f"[sync] Falha ao atualizar mirror: {exc}")
        await asyncio.sleep(max(settings.sync_interval_seconds, 60))


@app.on_event("startup")
async def start_primary_sync_loop():
    if (
        settings.sync_mode == "primary"
        and settings.sync_auto_push
        and settings.sync_target_url
        and settings.sync_token
    ):
        import asyncio

        asyncio.create_task(_sync_mirror_loop())


@app.middleware("http")
async def mirror_read_only_guard(request: Request, call_next):
    if (
        settings.sync_mode == "mirror"
        and settings.mirror_read_only
        and request.method not in {"GET", "HEAD", "OPTIONS"}
    ):
        path = request.url.path
        allowed_paths = {"/login", "/logout"}
        if not path.startswith("/api/sync/") and path not in allowed_paths:
            return JSONResponse(
                {
                    "detail": (
                        "Ambiente online em modo espelho. "
                        "As alteracoes devem ser feitas no servidor local principal."
                    )
                },
                status_code=423,
            )
    return await call_next(request)


@app.middleware("http")
async def browser_security(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        source = request.headers.get("origin") or request.headers.get("referer")
        if source:
            source_host = urlsplit(source).netloc.lower()
            request_host = request.headers.get(
                "x-forwarded-host", request.headers.get("host", "")
            ).split(",")[0].strip().lower()
            if source_host != request_host:
                return JSONResponse({"detail": "Origem do pedido inválida."}, status_code=403)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; font-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    )
    return response

for router in [auth.router, dashboard.router, products.router, movements.router, requisitions.router, procurement.router, hse.router, internal_ops.router, settings_router.router, preferences.router, reports.router, users.router, profiles.router, imports.router, audit.router, notifications.router, documents.router, sync.router, about.router]:
    app.include_router(router)


@app.get("/")
def root(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    return RedirectResponse("/login", status_code=303)
