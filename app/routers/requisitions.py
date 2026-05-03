from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import Department, Product, Requisition, RequisitionItem, RequisitionStatus, Role, User
from app.routers.common import templates
from app.security import current_user, operational_roles, require_roles
from app.services.audit import audit_log
from app.services.inventory import StockError
from app.services.notifications import notify_requisition_decision, notify_requisition_pending
from app.services.requisition_pdf import requisition_to_pdf
from app.services.requisitions import issue_requisition, next_requisition_number
from app.services.transactions import atomic

router = APIRouter(prefix="/requisicoes", tags=["requisicoes"])


MANAGER_ROLES = ("SuperAdmin", "Admin", "Editor", "Gestor de Estoque", "Chefe do Terminal")


def manager_options(db: Session) -> list[User]:
    return db.scalars(
        select(User).where(User.is_active == True, User.role.has(Role.name.in_(MANAGER_ROLES))).order_by(User.full_name)
    ).all()


def default_manager_id(user: User, managers: list[User]) -> int | None:
    if user.role.name in MANAGER_ROLES:
        return user.id
    return managers[0].id if managers else None


@router.get("")
def list_requisitions(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(Requisition).order_by(Requisition.request_date.desc())
    if user.role.name == "User":
        stmt = stmt.where(Requisition.requesting_user_id == user.id)
    return templates.TemplateResponse("requisitions/index.html", {"request": request, "user": user, "requisitions": db.scalars(stmt).all()})


@router.get("/nova")
def new_requisition(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    managers = manager_options(db)
    return templates.TemplateResponse(
        "requisitions/form.html",
        {
            "request": request,
            "user": user,
            "products": db.scalars(select(Product).where(Product.status == "active").order_by(Product.name)).all(),
            "departments": db.scalars(select(Department).order_by(Department.name)).all(),
            "managers": managers,
            "default_manager_id": default_manager_id(user, managers),
            "authorization_person": "Gestor de Estoque",
            "error": None,
        },
    )


@router.post("/nova")
def create_requisition(
    request: Request,
    department_id: int | None = Form(None),
    operational_manager_id: int | None = Form(None),
    req_type: str = Form("REQUISIÇÃO"),
    product_id: list[int] = Form(...),
    quantity: list[float] = Form(...),
    observation: list[str] = Form([]),
    submit: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    manager = db.get(User, operational_manager_id) if operational_manager_id else None
    with atomic(db):
        req = Requisition(
            number=next_requisition_number(db),
            requesting_user_id=user.id,
            department_id=department_id or user.department_id,
            operational_manager=manager.full_name if manager else None,
            authorization_person="Gestor de Estoque",
            req_type=req_type,
            status=RequisitionStatus.submitted.value if submit else RequisitionStatus.draft.value,
        )
        db.add(req)
        db.flush()
        department_name = req.department.name if req.department else None
        for idx, pid in enumerate(product_id):
            if quantity[idx] <= 0:
                continue
            db.add(
                RequisitionItem(
                    requisition_id=req.id,
                    product_id=pid,
                    quantity_requested=quantity[idx],
                    destination=department_name,
                    observation=observation[idx] if idx < len(observation) else None,
                )
            )
        if submit:
            notify_requisition_pending(db, req)
        audit_log(db, user, "Criou requisição", "Requisições", req.number, request=request)
    return RedirectResponse(f"/requisicoes/{req.id}", status_code=303)


@router.get("/{req_id}")
def view_requisition(req_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    req = db.get(Requisition, req_id)
    if not req:
        raise HTTPException(404)
    if user.role.name == "User" and req.requesting_user_id != user.id:
        raise HTTPException(403)
    return templates.TemplateResponse("requisitions/detail.html", {"request": request, "user": user, "req": req, "error": None})


@router.post("/{req_id}/submit")
def submit_requisition(req_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    req = db.get(Requisition, req_id)
    if not req or (user.role.name == "User" and req.requesting_user_id != user.id):
        raise HTTPException(404)
    with atomic(db):
        req.status = RequisitionStatus.submitted.value
        notify_requisition_pending(db, req)
        audit_log(db, user, "Submeteu requisição", "Requisições", req.number, request=request)
    return RedirectResponse(f"/requisicoes/{req.id}", status_code=303)


@router.post("/{req_id}/review")
def review_requisition(
    req_id: int,
    request: Request,
    decision: str = Form(...),
    rejection_reason: str | None = Form(None),
    item_id: list[int] = Form([]),
    approved_quantity: list[float] = Form([]),
    review_observation: list[str] = Form([]),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*operational_roles())),
):
    req = db.get(Requisition, req_id)
    if not req:
        raise HTTPException(404)
    try:
        with atomic(db):
            req.reviewed_by_id = user.id
            req.reviewed_at = datetime.now(timezone.utc)

            if decision == "reject":
                req.status = RequisitionStatus.rejected.value
                req.notes = rejection_reason or req.notes
                for item in req.items:
                    item.quantity_issued = 0
                    item.review_status = "Rejeitado"
                    item.review_observation = rejection_reason or "Requisição rejeitada."
                notify_requisition_decision(db, req, user, "Rejeitada")
            elif decision == "approve":
                req.status = RequisitionStatus.approved.value
                issue_requisition(db, req, user)
                notify_requisition_decision(db, req, user, "Emitida")
            else:
                req.status = RequisitionStatus.approved.value
                quantities = {item_id[idx]: approved_quantity[idx] for idx in range(min(len(item_id), len(approved_quantity)))}
                notes = {item_id[idx]: review_observation[idx] for idx in range(min(len(item_id), len(review_observation)))}
                issue_requisition(db, req, user, approved_quantities=quantities, review_notes=notes)
                req.notes = rejection_reason or req.notes
                notify_requisition_decision(db, req, user, req.status)

            audit_log(
                db,
                user,
                "Aprovou/Rejeitou requisição",
                "Requisições",
                req.number,
                new_value={"status": req.status, "decision": decision},
                request=request,
            )
    except StockError as exc:
        return templates.TemplateResponse("requisitions/detail.html", {"request": request, "user": user, "req": req, "error": str(exc)}, status_code=400)
    return RedirectResponse(f"/requisicoes/{req.id}", status_code=303)


@router.post("/{req_id}/issue")
def issue(req_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(*operational_roles()))):
    req = db.get(Requisition, req_id)
    if not req:
        raise HTTPException(404)
    try:
        with atomic(db):
            issue_requisition(db, req, user)
            audit_log(db, user, "Emitiu requisição", "Requisições", req.number, request=request)
    except StockError as exc:
        return templates.TemplateResponse("requisitions/detail.html", {"request": request, "user": user, "req": req, "error": str(exc)}, status_code=400)
    return RedirectResponse(f"/requisicoes/{req.id}", status_code=303)


@router.get("/{req_id}/pdf")
def requisition_pdf(req_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    req = db.get(Requisition, req_id)
    if not req:
        raise HTTPException(404)
    return Response(requisition_to_pdf(req), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{req.number}.pdf"'})
