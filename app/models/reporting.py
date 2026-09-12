"""Operational reporting additions. Legacy source tables remain unchanged."""
from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.models.core import utc_now


class DepartmentReportTables(Base):
    __tablename__ = 'department_report_tables'
    report_id: Mapped[int] = mapped_column(ForeignKey('department_daily_reports.id'), primary_key=True)
    payload: Mapped[str] = mapped_column(Text, default='{}')


class OperationalReport(Base):
    __tablename__ = 'operational_reports'
    __table_args__ = (UniqueConstraint('series_key', 'version'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    series_key: Mapped[str] = mapped_column(String(180), index=True)
    number: Mapped[str] = mapped_column(String(80), unique=True)
    period: Mapped[str] = mapped_column(String(20))
    department_key: Mapped[str] = mapped_column(String(30), index=True)
    date_from: Mapped[date] = mapped_column(Date, index=True)
    date_to: Mapped[date] = mapped_column(Date, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default='Generated', index=True)
    source_daily_id: Mapped[int | None] = mapped_column(ForeignKey('department_daily_reports.id'))
    snapshot: Mapped[str] = mapped_column(Text, default='{}')
    supplements: Mapped[str] = mapped_column(Text, default='{}')
    pdf: Mapped[bytes | None] = mapped_column(LargeBinary)
    docx: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_by_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    submitted_by_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __mapper_args__ = {'version_id_col': revision}


class ManagerReportSource(Base):
    __tablename__ = 'manager_report_sources'
    __table_args__ = (UniqueConstraint('fingerprint', 'version'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    import_id: Mapped[int] = mapped_column(ForeignKey('financial_daily_imports.id'), index=True)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey('manager_report_sources.id'), unique=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default='Draft')
    metrics: Mapped[str] = mapped_column(Text, default='[]')
    notes: Mapped[str] = mapped_column(Text, default='')
    extraction_warning: Mapped[str] = mapped_column(Text, default='')
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {'version_id_col': revision}


class DailyReportEntry(Base):
    __tablename__ = 'daily_report_entries'
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey('department_daily_reports.id'), index=True)
    category: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(220))
    description: Mapped[str] = mapped_column(Text, default='')
    location: Mapped[str] = mapped_column(String(160), default='')
    equipment: Mapped[str] = mapped_column(String(160), default='')
    occurrence_key: Mapped[str] = mapped_column(String(100), default='')
    metric_key: Mapped[str] = mapped_column(String(60), default='')
    dimension: Mapped[str] = mapped_column(String(160), default='')
    value: Mapped[float | None] = mapped_column(Numeric(18, 4))
    requires_action: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[str] = mapped_column(String(20), default='Normal')
    owner_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    due_date: Mapped[date | None] = mapped_column(Date)


class OperationalPending(Base):
    __tablename__ = 'operational_pending_items'
    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(200), unique=True)
    department_key: Mapped[str] = mapped_column(String(30), index=True)
    title: Mapped[str] = mapped_column(String(220))
    description: Mapped[str] = mapped_column(Text, default='')
    camera_id: Mapped[int | None] = mapped_column(ForeignKey('cctv_cameras.id'))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    priority: Mapped[str] = mapped_column(String(20), default='Normal')
    status: Mapped[str] = mapped_column(String(30), default='Pending')
    due_date: Mapped[date | None] = mapped_column(Date)
    opened_on: Mapped[date] = mapped_column(Date, index=True)
    closed_on: Mapped[date | None] = mapped_column(Date)
    history: Mapped[str] = mapped_column(Text, default='[]')
    revision: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {'version_id_col': revision}


class CctvCamera(Base):
    __tablename__ = 'cctv_cameras'
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    area: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(String(220), default='')
    model: Mapped[str] = mapped_column(String(160), default='')
    nvr: Mapped[str] = mapped_column(String(160), default='')
    location: Mapped[str] = mapped_column(String(160), default='')
    product_id: Mapped[int | None] = mapped_column(ForeignKey('products.id'))
    registered_on: Mapped[date] = mapped_column(Date)
    retired_on: Mapped[date | None] = mapped_column(Date)


class CctvStatusLog(Base):
    __tablename__ = 'cctv_status_logs'
    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey('cctv_cameras.id'), index=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    status: Mapped[str] = mapped_column(String(160))
    operational: Mapped[bool] = mapped_column(Boolean)
    full_recording: Mapped[bool] = mapped_column(Boolean)
    needs_cleaning: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[str] = mapped_column(String(20), default='Normal')
    notes: Mapped[str] = mapped_column(Text, default='')
    created_by_id: Mapped[int] = mapped_column(ForeignKey('users.id'))


class CctvSchedule(Base):
    __tablename__ = 'cctv_schedules'
    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey('cctv_cameras.id'), index=True)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    interval_days: Mapped[int] = mapped_column(Integer, default=7)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    notes: Mapped[str] = mapped_column(Text, default='')


class CctvInspection(Base):
    __tablename__ = 'cctv_inspections'
    __table_args__ = (UniqueConstraint('schedule_id', 'scheduled_on'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey('cctv_schedules.id'), index=True)
    scheduled_on: Mapped[date] = mapped_column(Date, index=True)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    result: Mapped[str] = mapped_column(String(40))
    previous_status: Mapped[str] = mapped_column(String(160))
    notes: Mapped[str] = mapped_column(Text, default='')
    performed_by_id: Mapped[int] = mapped_column(ForeignKey('users.id'))


class OperationalReportSettings(Base):
    __tablename__ = 'operational_report_settings'
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    week_start: Mapped[int] = mapped_column(Integer, default=0)
    allow_partial: Mapped[bool] = mapped_column(Boolean, default=False)
