from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.core import (
    AuditLog,
    ImportErrorRow,
    Notification,
    Product,
    Requisition,
    RequisitionItem,
    StockDocument,
    StockDocumentProduct,
    StockMovement,
    User,
)


def clean_for_production(db: Session) -> User:
    superadmin = db.scalar(select(User).where(User.username == "superadmin"))
    if not superadmin:
        raise RuntimeError("O utilizador superadmin não existe.")

    for model in (
        Notification,
        AuditLog,
        ImportErrorRow,
        StockDocumentProduct,
        StockDocument,
        RequisitionItem,
        Requisition,
        StockMovement,
        Product,
    ):
        db.execute(delete(model))

    db.execute(delete(User).where(User.id != superadmin.id))
    superadmin.is_active = True
    superadmin.must_reset_password = False
    db.flush()
    return superadmin
