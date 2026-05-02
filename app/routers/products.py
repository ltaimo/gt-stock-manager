import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import Category, Department, Product, StockMovement, User
from app.routers.common import templates
from app.security import current_user, require_roles
from app.services.audit import audit_log
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
def new_product(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("SuperAdmin", "Admin"))):
    return templates.TemplateResponse("products/form.html", {"request": request, "user": user, "product": None, "categories": db.scalars(select(Category).order_by(Category.name)).all(), "next_code": next_product_code(db), "error": None, "duplicate": None})


@router.post("/novo")
def create_product(
    request: Request,
    name: str = Form(...),
    category_id: int | None = Form(None),
    unit: str = Form("un"),
    minimum_stock: float = Form(0),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("SuperAdmin", "Admin")),
):
    duplicate = db.scalar(select(Product).where(Product.name.ilike(name.strip())))
    if duplicate:
        return templates.TemplateResponse(
            "products/form.html",
            {
                "request": request,
                "user": user,
                "product": None,
                "categories": db.scalars(select(Category).order_by(Category.name)).all(),
                "next_code": next_product_code(db),
                "error": "Este produto já existe. Para aumentar o stock, registe uma Entrada em Movimentos.",
                "duplicate": duplicate,
            },
            status_code=400,
        )
    code = next_product_code(db)
    with atomic(db):
        product = Product(code=code.strip(), name=name.strip(), category_id=category_id, unit=unit, minimum_stock=minimum_stock, created_by_id=user.id)
        db.add(product)
        db.flush()
        audit_log(db, user, "Criou produto", "Produtos", product.id, new_value={"code": code, "name": name}, request=request)
    return RedirectResponse("/produtos", status_code=303)


@router.get("/{product_id}/editar")
def edit_product(product_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("SuperAdmin", "Admin"))):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404)
    return templates.TemplateResponse("products/form.html", {"request": request, "user": user, "product": product, "categories": db.scalars(select(Category).order_by(Category.name)).all()})


@router.post("/{product_id}/editar")
def update_product(
    product_id: int,
    request: Request,
    name: str = Form(...),
    category_id: int | None = Form(None),
    unit: str = Form("un"),
    minimum_stock: float = Form(0),
    status: str = Form("active"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("SuperAdmin", "Admin")),
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404)
    old = {"name": product.name, "minimum_stock": float(product.minimum_stock or 0), "status": product.status}
    with atomic(db):
        product.name = name.strip()
        product.category_id = category_id
        product.unit = unit
        product.minimum_stock = minimum_stock
        product.status = status
        audit_log(db, user, "Atualizou produto", "Produtos", product.id, old_value=old, new_value={"name": name, "minimum_stock": minimum_stock, "status": status}, request=request)
    return RedirectResponse("/produtos", status_code=303)


@router.post("/{product_id}/desativar")
def deactivate_product(product_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("SuperAdmin", "Admin"))):
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
def categories(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("SuperAdmin", "Admin"))):
    return templates.TemplateResponse("products/categories.html", {"request": request, "user": user, "categories": db.scalars(select(Category).order_by(Category.name)).all(), "departments": db.scalars(select(Department).order_by(Department.name)).all()})


@router.post("/categorias")
def add_category(name: str = Form(...), db: Session = Depends(get_db), user: User = Depends(require_roles("SuperAdmin", "Admin"))):
    normalized = name.strip().lower()
    if not db.scalar(select(Category).where(Category.normalized_name == normalized)):
        with atomic(db):
            category = Category(name=name.strip().title(), normalized_name=normalized)
            db.add(category)
            db.flush()
            audit_log(db, user, "Criou categoria", "Configurações", category.id, new_value={"name": category.name})
    return RedirectResponse("/produtos/categorias", status_code=303)


@router.post("/departamentos")
def add_department(name: str = Form(...), db: Session = Depends(get_db), user: User = Depends(require_roles("SuperAdmin", "Admin"))):
    if not db.scalar(select(Department).where(Department.name == name.strip().title())):
        with atomic(db):
            department = Department(name=name.strip().title())
            db.add(department)
            db.flush()
            audit_log(db, user, "Criou departamento", "Configurações", department.id, new_value={"name": department.name})
    return RedirectResponse("/produtos/categorias", status_code=303)
