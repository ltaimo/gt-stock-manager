import re
import secrets
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import get_settings
from app.models.core import Category, Department, Product, StockMovement, User
from app.routers.common import templates
from app.security import current_user, require_permission
from app.services.audit import audit_log
from app.services.forms import optional_float, optional_int, required_float, required_text
from app.services.inventory import StockError, adjust_product_stock
from app.services.transactions import atomic
from app.services.stock_reset import reset_all_stock

router = APIRouter(prefix="/produtos", tags=["produtos"])
settings = get_settings()


def next_product_code(db: Session) -> str:
    codes = [code for (code,) in db.execute(select(Product.code).where(Product.code.like("PRD-%"))).all()]
    max_number = 0
    for code in codes:
        match = re.match(r"PRD-(\d+)$", code)
        if match:
            max_number = max(max_number, int(match.group(1)))
    return f"PRD-{max_number + 1:05d}"


@router.get("")
def list_products(request: Request, q: str = "", status: str = "", db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(Product).outerjoin(Category)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Product.code.ilike(like), Product.name.ilike(like), Category.name.ilike(like)))
    if status:
        stmt = stmt.where(Product.status == status)
    products = db.scalars(stmt.order_by(Product.name)).all()
    return templates.TemplateResponse("products/index.html", {"request": request, "user": user, "products": products, "q": q, "status": status})


@router.get("/novo")
def new_product(request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("products_manage"))):
    return templates.TemplateResponse("products/form.html", {"request": request, "user": user, "product": None, "categories": db.scalars(select(Category).where(Category.is_active == True).order_by(Category.name)).all(), "next_code": next_product_code(db), "error": None, "duplicate": None})


@router.post("/novo")
def create_product(
    request: Request,
    name: str | None = Form(None),
    category_id: str | None = Form(None),
    unit: str = Form("un"),
    minimum_stock: str | None = Form("0"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("products_manage")),
):
    clean_name = required_text(name, "Nome do produto", 220)
    parsed_category_id = optional_int(category_id, "Categoria")
    parsed_minimum = optional_float(minimum_stock, "Stock mínimo", 0) or 0
    if parsed_minimum < 0:
        raise HTTPException(400, "Stock mínimo não pode ser negativo.")
    clean_unit = required_text(unit, "Unidade de medida", 30)
    if clean_unit not in {"un", "caixa", "embalagem", "rolo", "par", "garrafa", "resma", "kg", "g", "L", "ml", "m"}:
        raise HTTPException(400, "Unidade de medida inválida.")
    if parsed_category_id and not db.get(Category, parsed_category_id):
        raise HTTPException(400, "A categoria selecionada não existe.")
    duplicate = db.scalar(select(Product).where(Product.name.ilike(clean_name)))
    if duplicate:
        return templates.TemplateResponse(
            "products/form.html",
            {
                "request": request,
                "user": user,
                "product": None,
                "categories": db.scalars(select(Category).where(Category.is_active == True).order_by(Category.name)).all(),
                "next_code": next_product_code(db),
                "error": "Este produto já existe. Para aumentar o stock, registe uma Entrada em Movimentos.",
                "duplicate": duplicate,
            },
            status_code=400,
        )
    code = next_product_code(db)
    with atomic(db):
        product = Product(code=code.strip(), name=clean_name, category_id=parsed_category_id, unit=clean_unit, minimum_stock=parsed_minimum, created_by_id=user.id)
        db.add(product)
        db.flush()
        audit_log(db, user, "Criou produto", "Produtos", product.id, new_value={"code": code, "name": clean_name}, request=request)
    return RedirectResponse("/produtos", status_code=303)


@router.get("/{product_id}/editar")
def edit_product(product_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("products_manage"))):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404)
    return templates.TemplateResponse("products/form.html", {"request": request, "user": user, "product": product, "categories": db.scalars(select(Category).where((Category.is_active == True) | (Category.id == product.category_id)).order_by(Category.name)).all()})


@router.post("/{product_id}/editar")
def update_product(
    product_id: int,
    request: Request,
    name: str | None = Form(None),
    category_id: str | None = Form(None),
    unit: str = Form("un"),
    minimum_stock: str | None = Form("0"),
    status: str = Form("active"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("products_manage")),
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404)
    clean_name = required_text(name, "Nome do produto", 220)
    clean_unit = required_text(unit, "Unidade de medida", 30)
    if clean_unit not in {"un", "caixa", "embalagem", "rolo", "par", "garrafa", "resma", "kg", "g", "L", "ml", "m"}:
        raise HTTPException(400, "Unidade de medida inválida.")
    parsed_category_id = optional_int(category_id, "Categoria")
    parsed_minimum = optional_float(minimum_stock, "Stock mínimo", 0) or 0
    if parsed_minimum < 0:
        raise HTTPException(400, "Stock mínimo não pode ser negativo.")
    if parsed_category_id and not db.get(Category, parsed_category_id):
        raise HTTPException(400, "A categoria selecionada não existe.")
    if status not in {"active", "inactive"}:
        raise HTTPException(400, "Estado do produto inválido.")
    duplicate = db.scalar(
        select(Product).where(Product.name.ilike(clean_name), Product.id != product.id)
    )
    if duplicate:
        raise HTTPException(400, "Já existe outro produto com este nome.")
    old = {"name": product.name, "minimum_stock": float(product.minimum_stock or 0), "status": product.status}
    with atomic(db):
        product.name = clean_name
        product.category_id = parsed_category_id
        product.unit = clean_unit
        product.minimum_stock = parsed_minimum
        product.status = status
        audit_log(db, user, "Atualizou produto", "Produtos", product.id, old_value=old, new_value={"name": clean_name, "minimum_stock": parsed_minimum, "status": status}, request=request)
    return RedirectResponse("/produtos", status_code=303)


@router.post("/{product_id}/ajustar-stock")
def adjust_stock(
    product_id: int,
    request: Request,
    target_quantity: str | None = Form(None),
    reason: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("stock_adjust")),
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404)
    target = required_float(target_quantity, "Nova quantidade existente")
    clean_reason = required_text(reason, "Motivo do ajuste", 500)
    old_quantity = float(product.current_stock or 0)
    try:
        with atomic(db):
            movement = adjust_product_stock(
                db,
                product=product,
                target_quantity=target,
                reason=clean_reason,
                actor=user,
            )
            audit_log(
                db,
                user,
                "Ajustou stock do produto",
                "Stock",
                product.id,
                old_value={"quantity": old_quantity},
                new_value={
                    "quantity": target,
                    "reason": clean_reason,
                    "movement_id": movement.id,
                },
                request=request,
            )
    except StockError as exc:
        return templates.TemplateResponse(
            "products/form.html",
            {
                "request": request,
                "user": user,
                "product": product,
                "categories": db.scalars(select(Category).where((Category.is_active == True) | (Category.id == product.category_id)).order_by(Category.name)).all(),
                "adjustment_error": str(exc),
            },
            status_code=400,
        )
    return RedirectResponse(f"/produtos/{product.id}/editar?stock_adjusted=1", status_code=303)


@router.post("/{product_id}/desativar")
def deactivate_product(product_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("products_manage"))):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404)
    has_movements = db.scalar(select(StockMovement).where(StockMovement.product_id == product.id).limit(1))
    with atomic(db):
        if has_movements:
            product.status = "inactive"
        else:
            db.delete(product)
        audit_log(db, user, "Desativou/removeu produto", "Produtos", product.id, request=request)
    return RedirectResponse("/produtos", status_code=303)


@router.get("/categorias")
def categories(request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("settings_manage"))):
    return RedirectResponse("/configuracoes", status_code=303)


@router.post("/categorias")
def add_category(name: str | None = Form(None), db: Session = Depends(get_db), user: User = Depends(require_permission("settings_manage"))):
    clean_name = required_text(name, "Nome da categoria", 120)
    normalized = clean_name.lower()
    if not db.scalar(select(Category).where(Category.normalized_name == normalized)):
        with atomic(db):
            category = Category(name=clean_name.title(), normalized_name=normalized)
            db.add(category)
            db.flush()
            audit_log(db, user, "Criou categoria", "Configurações", category.id, new_value={"name": category.name})
    return RedirectResponse("/produtos/categorias", status_code=303)


@router.post("/departamentos")
def add_department(name: str | None = Form(None), db: Session = Depends(get_db), user: User = Depends(require_permission("settings_manage"))):
    clean_name = required_text(name, "Nome do departamento", 120)
    if not db.scalar(select(Department).where(Department.name == clean_name.title())):
        with atomic(db):
            department = Department(name=clean_name.title())
            db.add(department)
            db.flush()
            audit_log(db, user, "Criou departamento", "Configurações", department.id, new_value={"name": department.name})
    return RedirectResponse("/produtos/categorias", status_code=303)


@router.post("/stock/reset")
def reset_stock(
    request: Request,
    security_code: str = Form(...),
    confirmation: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("stock_reset")),
):
    configured_code = settings.reset_stock_security_code
    if not configured_code:
        message = quote("O código de segurança para reset de stock não está configurado.")
        return RedirectResponse(f"/produtos/categorias?reset_error={message}", status_code=303)
    if confirmation.strip().upper() != "RESETAR STOCK":
        message = quote('Escreva exatamente "RESETAR STOCK" para confirmar.')
        return RedirectResponse(f"/produtos/categorias?reset_error={message}", status_code=303)
    if not secrets.compare_digest(security_code.strip(), configured_code):
        message = quote("Código de segurança inválido.")
        return RedirectResponse(f"/produtos/categorias?reset_error={message}", status_code=303)

    with atomic(db):
        result = reset_all_stock(db, user)
        audit_log(
            db,
            user,
            "Resetou todo o stock",
            "Stock",
            "RESET-STOCK",
            new_value=result,
            request=request,
        )

    message = quote(
        f"Stock resetado com sucesso. Produtos afetados: {result['products_affected']}; "
        f"quantidade removida: {result['quantity_removed']:g}."
    )
    return RedirectResponse(f"/produtos/categorias?reset_message={message}", status_code=303)
