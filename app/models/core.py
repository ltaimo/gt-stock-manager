from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RoleName(str, Enum):
    superadmin = "SuperAdmin"
    admin = "Admin"
    editor = "Editor"
    user = "User"
    stock_manager = "Gestor de Estoque"
    terminal_chief = "Chefe do Terminal"


class ProductStatus(str, Enum):
    active = "active"
    inactive = "inactive"


class MovementAction(str, Enum):
    entrada = "ENTRADA"
    saida = "SAÍDA"
    devolucao = "DEVOLUÇÃO"
    acerto = "ACERTO"


class RequisitionStatus(str, Enum):
    draft = "Draft"
    submitted = "Submitted"
    approved = "Approved"
    rejected = "Rejected"
    issued = "Issued"
    partially_issued = "Emitido Parcialmente"
    cancelled = "Cancelled"


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    permissions: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    users: Mapped[list["User"]] = relationship(back_populates="role")


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_whatsapp: Mapped[bool] = mapped_column(Boolean, default=False)
    preferred_language: Mapped[str] = mapped_column(String(5), default="pt")
    must_reset_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    role: Mapped[Role] = relationship(back_populates="users")
    department: Mapped[Department | None] = relationship()


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(220), nullable=False, index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    unit: Mapped[str] = mapped_column(String(30), default="un")
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    current_stock: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    minimum_stock: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    total_entries: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    total_exits: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    status: Mapped[str] = mapped_column(String(20), default=ProductStatus.active.value)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    category: Mapped[Category | None] = relationship()
    created_by: Mapped[User | None] = relationship()
    movements: Mapped[list["StockMovement"]] = relationship(back_populates="product")

    @property
    def alert_status(self) -> str:
        current = float(self.current_stock or 0)
        minimum = float(self.minimum_stock or 0)
        if current < 0:
            return "Erro: Stock Negativo"
        if current == 0:
            return "Sem Stock"
        if minimum > 0 and current <= minimum:
            return "Stock Crítico"
        if minimum > 0 and current <= minimum * 1.5:
            return "Stock em Atenção"
        return "Stock Adequado"

    @property
    def alert_badge(self) -> str:
        return {
            "Stock Adequado": "green",
            "Stock em Atenção": "orange",
            "Stock Crítico": "red",
            "Sem Stock": "grey",
            "Erro: Stock Negativo": "red",
        }.get(self.alert_status, "grey")


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    action_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    signed_quantity: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    destination: Mapped[str | None] = mapped_column(String(180))
    responsible_person: Mapped[str | None] = mapped_column(String(160))
    requesting_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    registered_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    reference_number: Mapped[str | None] = mapped_column(String(80), index=True)
    override_authorized_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    product: Mapped[Product] = relationship(back_populates="movements")
    requesting_user: Mapped[User | None] = relationship(foreign_keys=[requesting_user_id])
    registered_by: Mapped[User] = relationship(foreign_keys=[registered_by_id])
    department: Mapped[Department | None] = relationship()


class Requisition(Base):
    __tablename__ = "requisitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    request_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    requesting_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    operational_manager: Mapped[str | None] = mapped_column(String(160))
    authorization_person: Mapped[str | None] = mapped_column(String(160))
    estimated_value: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    req_type: Mapped[str] = mapped_column(String(40), default="REQUISIÇÃO")
    status: Mapped[str] = mapped_column(String(30), default=RequisitionStatus.draft.value, index=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    requesting_user: Mapped[User] = relationship(foreign_keys=[requesting_user_id])
    department: Mapped[Department | None] = relationship()
    items: Mapped[list["RequisitionItem"]] = relationship(back_populates="requisition", cascade="all, delete-orphan")
    procurement_case: Mapped["ProcurementCase | None"] = relationship(back_populates="requisition", cascade="all, delete-orphan")


class RequisitionItem(Base):
    __tablename__ = "requisition_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requisition_id: Mapped[int] = mapped_column(ForeignKey("requisitions.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity_requested: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    quantity_issued: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    quantity_rejected: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    review_status: Mapped[str] = mapped_column(String(30), default="Pendente")
    destination: Mapped[str | None] = mapped_column(String(180))
    observation: Mapped[str | None] = mapped_column(Text)
    review_observation: Mapped[str | None] = mapped_column(Text)

    requisition: Mapped[Requisition] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    module: Mapped[str] = mapped_column(String(80), nullable=False)
    record_id: Mapped[str | None] = mapped_column(String(80))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    ip_device: Mapped[str | None] = mapped_column(String(220))

    user: Mapped[User | None] = relationship()


class ApprovalMatrixRule(Base):
    __tablename__ = "approval_matrix_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    min_value: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    max_value: Mapped[float | None] = mapped_column(Numeric(14, 2))
    modality: Mapped[str] = mapped_column(String(80), nullable=False)
    final_approval: Mapped[str] = mapped_column(String(160), nullable=False)
    approver_role_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    approver_role: Mapped[Role | None] = relationship()


class ProcurementCase(Base):
    __tablename__ = "procurement_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requisition_id: Mapped[int] = mapped_column(ForeignKey("requisitions.id"), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    justification: Mapped[str | None] = mapped_column(Text)
    cost_center: Mapped[str | None] = mapped_column(String(120))
    priority: Mapped[str] = mapped_column(String(30), default="Normal")
    item_type: Mapped[str] = mapped_column(String(40), default="Bem")
    technical_requirements: Mapped[str | None] = mapped_column(Text)
    hse_requirements: Mapped[str | None] = mapped_column(Text)
    tor_status: Mapped[str] = mapped_column(String(60), default="Pending HOD Approval")
    hod_approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    hod_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_manager_approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    terminal_manager_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_budget: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    required_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(80), default="Pending Budget Verification", index=True)
    budget_confirmed: Mapped[bool | None] = mapped_column(Boolean)
    budget_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    budget_verified_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    procurement_officer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    modality: Mapped[str | None] = mapped_column(String(80))
    approval_route: Mapped[str | None] = mapped_column(String(160))
    approval_status: Mapped[str] = mapped_column(String(60), default="Pending")
    rfq_rfp_tender_number: Mapped[str | None] = mapped_column(String(80))
    suppliers_invited: Mapped[int] = mapped_column(Integer, default=0)
    quotations_received: Mapped[int] = mapped_column(Integer, default=0)
    technical_evaluation_required: Mapped[bool] = mapped_column(Boolean, default=False)
    technical_evaluation_status: Mapped[str] = mapped_column(String(60), default="Not Required")
    technical_report_status: Mapped[str] = mapped_column(String(60), default="Pending")
    financial_evaluation_status: Mapped[str] = mapped_column(String(60), default="Pending")
    bid_analysis_status: Mapped[str] = mapped_column(String(60), default="Pending")
    hse_documents_status: Mapped[str] = mapped_column(String(60), default="Not Required")
    selected_supplier: Mapped[str | None] = mapped_column(String(180))
    po_number: Mapped[str | None] = mapped_column(String(80))
    po_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    po_value: Mapped[float | None] = mapped_column(Numeric(14, 2))
    receipt_status: Mapped[str] = mapped_column(String(60), default="Pending")
    execution_status: Mapped[str] = mapped_column(String(60), default="Not Started")
    receipt_note: Mapped[str | None] = mapped_column(Text)
    archive_status: Mapped[str] = mapped_column(String(60), default="Pending")
    closure_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comments: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    requisition: Mapped[Requisition] = relationship(back_populates="procurement_case")
    budget_verified_by: Mapped[User | None] = relationship(foreign_keys=[budget_verified_by_id])
    procurement_officer: Mapped[User | None] = relationship(foreign_keys=[procurement_officer_id])
    hod_approved_by: Mapped[User | None] = relationship(foreign_keys=[hod_approved_by_id])
    terminal_manager_approved_by: Mapped[User | None] = relationship(foreign_keys=[terminal_manager_approved_by_id])


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    module: Mapped[str] = mapped_column(String(80), nullable=False)
    record_id: Mapped[str | None] = mapped_column(String(80))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class StockDocument(Base):
    __tablename__ = "stock_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_type: Mapped[str] = mapped_column(String(40), default="Guia")
    document_number: Mapped[str | None] = mapped_column(String(120))
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    uploaded_by: Mapped[User] = relationship()
    products: Mapped[list["StockDocumentProduct"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class StockDocumentProduct(Base):
    __tablename__ = "stock_document_products"
    __table_args__ = (UniqueConstraint("document_id", "product_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("stock_documents.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)

    document: Mapped[StockDocument] = relationship(back_populates="products")
    product: Mapped[Product] = relationship()


class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    value: Mapped[str | None] = mapped_column(Text)


class ImportErrorRow(Base):
    __tablename__ = "import_error_rows"
    __table_args__ = (UniqueConstraint("batch_id", "row_number", "module"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    module: Mapped[str] = mapped_column(String(40), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    raw_data: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
