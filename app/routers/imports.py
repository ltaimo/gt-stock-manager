from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.i18n import language_for, translate_message, translate_text
from app.models.core import User
from app.routers.common import templates
from app.security import require_permission
from app.services.audit import audit_log
from app.services.exports import rows_to_csv
from app.services.imports import build_import_preview, import_preview, load_preview
from app.services.inventory import StockError
from app.services.transactions import atomic

router = APIRouter(prefix="/importar", tags=["importar"])


@router.get("")
def import_home(request: Request, user: User = Depends(require_permission("imports"))):
    return templates.TemplateResponse(request, "imports/index.html", {"request": request, "user": user})


@router.post("/preview")
async def preview_import(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("imports")),
):
    content = await file.read()
    try:
        preview = build_import_preview(db, file.filename, content)
    except Exception as exc:
        return templates.TemplateResponse(request, "imports/index.html",
            {"request": request, "user": user, "error": f"Não foi possível ler o ficheiro: {exc}"},
            status_code=400,
        )
    return RedirectResponse(f"/importar/preview/{preview['batch_id']}", status_code=303)


@router.get("/preview/{batch_id}")
def preview_page(batch_id: str, request: Request, user: User = Depends(require_permission("imports"))):
    try:
        preview = load_preview(batch_id)
    except FileNotFoundError:
        raise HTTPException(404, "Preview de importação não encontrado.")
    return templates.TemplateResponse(request, "imports/preview.html", {"request": request, "user": user, "preview": preview})


@router.post("/confirm/{batch_id}")
def confirm_import(
    batch_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("imports")),
):
    try:
        preview = load_preview(batch_id)
    except FileNotFoundError:
        raise HTTPException(404, "Preview de importação não encontrado.")

    if preview["errors"]:
        return RedirectResponse(f"/importar/preview/{batch_id}", status_code=303)

    try:
        with atomic(db):
            result = import_preview(db, preview, user)
            audit_log(
                db,
                user,
                "Confirmou importação",
                "Importação",
                batch_id,
                new_value={"imported": result.imported, "products": preview["counts"]["products_valid"], "users": preview["counts"]["users_valid"], "movements": preview["counts"]["movements_valid"]},
                request=request,
            )
    except StockError as exc:
        preview["errors"].append({"module": "Confirmação", "row": "", "error": str(exc), "data": {}})
        return templates.TemplateResponse(request, "imports/preview.html", {"request": request, "user": user, "preview": preview}, status_code=400)

    return templates.TemplateResponse(request, "imports/complete.html", {"request": request, "user": user, "preview": preview, "result": result})


@router.get("/falhas/{batch_id}.csv")
def failed_rows(batch_id: str, user: User = Depends(require_permission("imports"))):
    language = language_for(user)
    try:
        preview = load_preview(batch_id)
    except FileNotFoundError:
        raise HTTPException(404, "Preview de importação não encontrado.")
    rows = [(translate_text(e["module"], language), e["row"], translate_message(e["error"], language), e["data"]) for e in preview["errors"]]
    return Response(
        rows_to_csv([translate_text(value, language) for value in ["Módulo", "Linha", "Erro", "Dados"]], rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="erros_importacao.csv"'},
    )
