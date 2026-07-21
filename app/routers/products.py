import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import Category, Product, StockMovement, User
from app.routers.common import templates
from app.security import current_user, require_permission
from app.services.audit import audit_log
from app.services.forms import optional_float, optional_int, required_float, required_text
from app.services.inventory import (
    StockError,
    active_warehouses,
    adjust_product_stock,
    default_warehouse,
    warehouse_breakdown,
    warehouse_stock_map,
)
from app.services.transactions import atomic

router = APIRouter(prefix="/produtos", tags=["produtos"])


def next_product_code(db: Session) -> str:
    codes = [code for (code,) in db.execute(select(Product.code).where(Product.code.like("PRD-%"))).all()]
    max_number = 0
    for code in codes:
        match = re.match(r"PRD-(\d+)$", code)
        if match:
            max_number = max(max_number, int(match.group(1)))
    return f"PRD-{max_number + 1:05d}"


def product_categories(db: Session, product: Product | None = None) -> list[Category]:
    stmt = select(Category)
    if product and product.category_id:
        stmt = stmt.where((Category.is_active == True) | (Category.id == product.category_id))
    else:
        stmt = stmt.where(Category.is_active == True)
    return db.scalars(stmt.order_by(Category.name)).all()


def product_form_context(
    request: Request,
    db: Session,
    user: User,
    product: Product | None,
    **extra,
) -> dict:
    stock_by_warehouse = warehouse_stock_map(db, [product]).get(product.id, {}) if product else {}
    context = {
        "request": request,
        "user": user,
        "product": product,
        "categories": product_categories(db, product),
        "warehouses": active_warehouses(db),
        "default_warehouse_id": default_warehouse(db).id,
        "stock_by_warehouse": stock_by_warehouse,
        "next_code": next_product_code(db) if product is None else None,
        "error": None,
        "duplicate": None,
        "adjustment_error": None,
    }
    context.update(extra)
    return context


@router.get("")
def list_products(request: Request, q: str = "", status: str = "", db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(Product).outerjoin(Category)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Product.code.ilike(like),
                Product.name.ilike(like),
                Product.name_en.ilike(like),
                Category.name.ilike(like),
                Category.name_en.ilike(like),
            )
        )
    if status:
        stmt = stmt.where(Product.status == status)
    products = db.scalars(stmt.order_by(Product.name)).all()
    return templates.TemplateResponse(
        request,
        "products/index.html",
        {
            "request": request,
            "user": user,
            "products": products,
            "q": q,
            "status": status,
            "warehouse_breakdown": lambda product: warehouse_breakdown(db, product),
        },
    )


@router.get("/novo")
def new_product(request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("products_manage"))):
    return templates.TemplateResponse(request, "products/form.html", product_form_context(request, db, user, None))


@router.post("/novo")
def create_product(
    request: Request,
    name: str | None = Form(None),
    name_en: str | None = Form(None),
    category_id: str | None = Form(None),
    unit: str = Form("un"),
    unit_price: str | None = Form("0"),
    minimum_stock: str | None = Form("0"),
    requires_stock_control: str | None = Form("1"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("products_manage")),
):
    clean_name = required_text(name, "Nome do produto", 220)
    clean_name_en = required_text(name_en, "Nome do produto em inglês", 220) if str(name_en or "").strip() else None
    parsed_category_id = optional_int(category_id, "Categoria")
    parsed_minimum = optional_float(minimum_stock, "Stock mínimo", 0) or 0
    parsed_price = optional_float(unit_price, "Preço unitário", 0) or 0
    if parsed_minimum < 0:
        raise HTTPException(400, "Stock mínimo não pode ser negativo.")
    if parsed_price < 0:
        raise HTTPException(400, "Preço unitário não pode ser negativo.")
    clean_unit = required_text(unit, "Unidade de medida", 30)
    if clean_unit not in {"un", "caixa", "embalagem", "rolo", "par", "garrafa", "resma", "kg", "g", "L", "ml", "m"}:
        raise HTTPException(400, "Unidade de medida inválida.")
    if parsed_category_id and not db.get(Category, parsed_category_id):
        raise HTTPException(400, "A categoria selecionada não existe.")
    duplicate = db.scalar(select(Product).where(Product.name.ilike(clean_name)))
    if duplicate:
        return templates.TemplateResponse(
            request,
            "products/form.html",
            product_form_context(
                request,
                db,
                user,
                None,
                error="Este produto já existe. Para aumentar o stock, registe uma entrada em Movimentos.",
                duplicate=duplicate,
            ),
            status_code=400,
        )
    code = next_product_code(db)
    with atomic(db):
        product = Product(
            code=code.strip(),
            name=clean_name,
            name_en=clean_name_en,
            category_id=parsed_category_id,
            unit=clean_unit,
            unit_price=parsed_price,
            minimum_stock=parsed_minimum,
            requires_stock_control=requires_stock_control == "1",
            created_by_id=user.id,
        )
        db.add(product)
        db.flush()
        audit_log(db, user, "Criou produto", "Produtos", product.id, new_value={"code": code, "name": clean_name, "unit_price": parsed_price}, request=request)
    return RedirectResponse("/produtos", status_code=303)


@router.get("/{product_id}/editar")
def edit_product(product_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("products_manage"))):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "products/form.html", product_form_context(request, db, user, product))


@router.post("/{product_id}/editar")
def update_product(
    product_id: int,
    request: Request,
    name: str | None = Form(None),
    name_en: str | None = Form(None),
    category_id: str | None = Form(None),
    unit: str = Form("un"),
    unit_price: str | None = Form("0"),
    minimum_stock: str | None = Form("0"),
    requires_stock_control: str | None = Form(None),
    status: str = Form("active"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("products_manage")),
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404)
    clean_name = required_text(name, "Nome do produto", 220)
    clean_name_en = required_text(name_en, "Nome do produto em inglês", 220) if str(name_en or "").strip() else None
    clean_unit = required_text(unit, "Unidade de medida", 30)
    if clean_unit not in {"un", "caixa", "embalagem", "rolo", "par", "garrafa", "resma", "kg", "g", "L", "ml", "m"}:
        raise HTTPException(400, "Unidade de medida inválida.")
    parsed_category_id = optional_int(category_id, "Categoria")
    parsed_minimum = optional_float(minimum_stock, "Stock mínimo", 0) or 0
    parsed_price = optional_float(unit_price, "Preço unitário", 0) or 0
    if parsed_minimum < 0:
        raise HTTPException(400, "Stock mínimo não pode ser negativo.")
    if parsed_price < 0:
        raise HTTPException(400, "Preço unitário não pode ser negativo.")
    if parsed_category_id and not db.get(Category, parsed_category_id):
        raise HTTPException(400, "A categoria selecionada não existe.")
    if status not in {"active", "inactive"}:
        raise HTTPException(400, "Estado do produto inválido.")
    duplicate = db.scalar(select(Product).where(Product.name.ilike(clean_name), Product.id != product.id))
    if duplicate:
        raise HTTPException(400, "Já existe outro produto com este nome.")
    old = {
        "name": product.name,
        "name_en": product.name_en,
        "unit_price": float(product.unit_price or 0),
        "minimum_stock": float(product.minimum_stock or 0),
        "requires_stock_control": product.requires_stock_control,
        "status": product.status,
    }
    with atomic(db):
        product.name = clean_name
        product.name_en = clean_name_en
        product.category_id = parsed_category_id
        product.unit = clean_unit
        product.unit_price = parsed_price
        product.minimum_stock = parsed_minimum
        product.requires_stock_control = requires_stock_control == "1"
        product.status = status
        audit_log(
            db,
            user,
            "Atualizou produto",
            "Produtos",
            product.id,
            old_value=old,
            new_value={
                "name": clean_name,
                "name_en": clean_name_en,
                "unit_price": parsed_price,
                "minimum_stock": parsed_minimum,
                "requires_stock_control": product.requires_stock_control,
                "status": status,
            },
            request=request,
        )
    return RedirectResponse("/produtos", status_code=303)


@router.post("/{product_id}/ajustar-stock")
def adjust_stock(
    product_id: int,
    request: Request,
    warehouse_id: str | None = Form(None),
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
    parsed_warehouse_id = optional_int(warehouse_id, "Armazém")
    try:
        with atomic(db):
            movement = adjust_product_stock(
                db,
                product=product,
                target_quantity=target,
                reason=clean_reason,
                actor=user,
                warehouse_id=parsed_warehouse_id,
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
                    "warehouse_id": movement.warehouse_id,
                },
                request=request,
            )
    except StockError as exc:
        return templates.TemplateResponse(
            request,
            "products/form.html",
            product_form_context(request, db, user, product, adjustment_error=str(exc)),
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
