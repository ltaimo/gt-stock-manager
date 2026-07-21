import secrets

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import get_settings
from app.maintenance.migrate_schema import ensure_schema
from app.services.sync import apply_snapshot, create_snapshot


router = APIRouter(prefix="/api/sync", tags=["sync"])


def require_sync_token(x_gtims_sync_token: str = Header(default="")) -> None:
    settings = get_settings()
    if not settings.sync_token:
        raise HTTPException(status_code=404, detail="Sincronizacao nao configurada.")
    if not secrets.compare_digest(x_gtims_sync_token, settings.sync_token):
        raise HTTPException(status_code=403, detail="Token de sincronizacao invalido.")


@router.get("/snapshot")
def snapshot(x_gtims_sync_token: str = Header(default="")):
    require_sync_token(x_gtims_sync_token)
    return create_snapshot()


@router.post("/mirror")
async def apply_mirror_snapshot(request: Request, x_gtims_sync_token: str = Header(default="")):
    settings = get_settings()
    require_sync_token(x_gtims_sync_token)
    if settings.sync_mode != "mirror":
        raise HTTPException(status_code=409, detail="Este ambiente nao esta em modo mirror.")
    ensure_schema()
    payload = await request.json()
    try:
        counts = apply_snapshot(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "tables": counts}
