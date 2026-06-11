from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.database import Base, engine
from app.errors import http_error_handler, unexpected_error_handler, validation_error_handler
from app.maintenance.migrate_schema import ensure_schema
from app.routers import about, audit, auth, dashboard, documents, imports, movements, notifications, products, reports, requisitions, users


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

for router in [auth.router, dashboard.router, products.router, movements.router, requisitions.router, reports.router, users.router, imports.router, audit.router, notifications.router, documents.router, about.router]:
    app.include_router(router)


@app.get("/")
def root(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    return RedirectResponse("/login", status_code=303)
