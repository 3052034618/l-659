from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Float, ForeignKey, Date, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(200), unique=True, nullable=False)
    full_name = Column(String(100), nullable=False)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=True)
    department = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True)
    role = Column(String(50), default="user")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    position = relationship("Position", back_populates="users")
    snapshots = relationship("PermissionSnapshot", back_populates="user", cascade="all, delete-orphan")
    deviations = relationship("PermissionDeviation", back_populates="user", foreign_keys="PermissionDeviation.user_id", cascade="all, delete-orphan")
    tickets_assigned = relationship("AuditTicket", back_populates="assignee", foreign_keys="AuditTicket.assignee_id")


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    code = Column(String(50), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    department = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    users = relationship("User", back_populates="position")
    permission_matrix = relationship("PermissionMatrix", back_populates="position", cascade="all, delete-orphan")


class PermissionMatrix(Base):
    __tablename__ = "permission_matrix"

    id = Column(Integer, primary_key=True, autoincrement=True)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=False)
    system_code = Column(String(50), nullable=False, index=True)
    permission_code = Column(String(200), nullable=False)
    permission_name = Column(String(200), nullable=False)
    permission_type = Column(String(50), default="read")
    is_required = Column(Boolean, default=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    position = relationship("Position", back_populates="permission_matrix")


class PermissionSnapshot(Base):
    __tablename__ = "permission_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    system_code = Column(String(50), nullable=False, index=True)
    snapshot_date = Column(Date, nullable=False, index=True)
    permissions = Column(JSON, nullable=False)
    sync_source = Column(String(200), nullable=True)
    is_processed = Column(Boolean, default=False)
    sync_status = Column(String(20), default="success")
    skip_reason = Column(String(500), nullable=True)
    audit_batch_id = Column(Integer, ForeignKey("special_audits.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("User", back_populates="snapshots")
    deviations = relationship("PermissionDeviation", back_populates="snapshot", cascade="all, delete-orphan")
    audit_batch = relationship("SpecialAudit", back_populates="snapshots")


class PermissionDeviation(Base):
    __tablename__ = "permission_deviations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    snapshot_id = Column(Integer, ForeignKey("permission_snapshots.id"), nullable=False)
    system_code = Column(String(50), nullable=False, index=True)
    permission_code = Column(String(200), nullable=False)
    permission_name = Column(String(200), nullable=False)
    deviation_type = Column(String(20), nullable=False)
    standard_value = Column(Boolean, default=False)
    actual_value = Column(Boolean, default=False)
    risk_score = Column(Float, default=0)
    risk_level = Column(String(20), default="low")
    status = Column(String(20), default="pending")
    description = Column(Text, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_action = Column(String(50), nullable=True)
    audit_batch_id = Column(Integer, ForeignKey("special_audits.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    user = relationship("User", back_populates="deviations", foreign_keys=[user_id])
    snapshot = relationship("PermissionSnapshot", back_populates="deviations")
    ticket = relationship("AuditTicket", back_populates="deviation", uselist=False, cascade="all, delete-orphan")
    audit_batch = relationship("SpecialAudit", back_populates="deviations")


class AuditTicket(Base):
    __tablename__ = "audit_tickets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_no = Column(String(50), unique=True, nullable=False)
    deviation_id = Column(Integer, ForeignKey("permission_deviations.id"), nullable=False)
    title = Column(String(500), nullable=False)
    status = Column(String(20), default="pending")
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    priority = Column(String(20), default="normal")
    escalated = Column(Boolean, default=False)
    escalated_at = Column(DateTime, nullable=True)
    escalated_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    remarks = Column(Text, nullable=True)
    resolution = Column(Text, nullable=True)
    action_type = Column(String(50), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    audit_batch_id = Column(Integer, ForeignKey("special_audits.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    deviation = relationship("PermissionDeviation", back_populates="ticket")
    assignee = relationship("User", back_populates="tickets_assigned", foreign_keys=[assignee_id])
    audit_batch = relationship("SpecialAudit", back_populates="tickets")


class PermissionChangeHistory(Base):
    __tablename__ = "permission_change_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    system_code = Column(String(50), nullable=False, index=True)
    permission_code = Column(String(200), nullable=False)
    change_type = Column(String(20), nullable=False)
    old_value = Column(Boolean, default=False)
    new_value = Column(Boolean, default=False)
    operator = Column(String(100), nullable=True)
    change_reason = Column(Text, nullable=True)
    source = Column(String(100), nullable=True)
    audit_batch_id = Column(Integer, ForeignKey("special_audits.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.now, index=True)

    audit_batch = relationship("SpecialAudit", back_populates="change_histories")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String(100), nullable=True)
    action = Column(String(100), nullable=False)
    action_type = Column(String(50), nullable=True)
    target_type = Column(String(50), nullable=True)
    target_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(50), nullable=True)
    status = Column(String(20), default="success")
    created_at = Column(DateTime, default=datetime.now, index=True)


class ComplianceReport(Base):
    __tablename__ = "compliance_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_date = Column(Date, unique=True, nullable=False)
    report_type = Column(String(50), default="daily")
    total_deviations = Column(Integer, default=0)
    high_risk_count = Column(Integer, default=0)
    medium_risk_count = Column(Integer, default=0)
    low_risk_count = Column(Integer, default=0)
    resolved_count = Column(Integer, default=0)
    pending_count = Column(Integer, default=0)
    avg_fix_hours = Column(Float, default=0)
    audit_completion_rate = Column(Float, default=0)
    system_stats = Column(JSON, nullable=True)
    pdf_path = Column(String(500), nullable=True)
    excel_path = Column(String(500), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)


class SpecialAudit(Base):
    __tablename__ = "special_audits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_no = Column(String(50), unique=True, nullable=False)
    batch_no = Column(String(50), unique=True, nullable=False, index=True)
    title = Column(String(500), nullable=False)
    audit_type = Column(String(50), default="manual")
    target_user_ids = Column(JSON, nullable=True)
    target_system_codes = Column(JSON, nullable=True)
    initiator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(20), default="running")
    result_summary = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    snapshots = relationship("PermissionSnapshot", back_populates="audit_batch")
    deviations = relationship("PermissionDeviation", back_populates="audit_batch")
    tickets = relationship("AuditTicket", back_populates="audit_batch")
    change_histories = relationship("PermissionChangeHistory", back_populates="audit_batch")
