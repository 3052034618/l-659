from datetime import datetime, date
from typing import Optional, List, Any
from pydantic import BaseModel, Field


class UserBase(BaseModel):
    username: str = Field(..., max_length=100)
    email: str = Field(..., max_length=200)
    full_name: str = Field(..., max_length=100)
    position_id: Optional[int] = None
    department: Optional[str] = None
    is_active: bool = True
    role: str = "user"


class UserCreate(UserBase):
    pass


class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    position_id: Optional[int] = None
    department: Optional[str] = None
    is_active: Optional[bool] = None
    role: Optional[str] = None


class UserResponse(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PositionBase(BaseModel):
    name: str = Field(..., max_length=100)
    code: str = Field(..., max_length=50)
    description: Optional[str] = None
    department: Optional[str] = None


class PositionCreate(PositionBase):
    pass


class PositionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    department: Optional[str] = None


class PositionResponse(PositionBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PermissionMatrixBase(BaseModel):
    position_id: int
    system_code: str = Field(..., max_length=50)
    permission_code: str = Field(..., max_length=200)
    permission_name: str = Field(..., max_length=200)
    permission_type: str = "read"
    is_required: bool = True
    description: Optional[str] = None


class PermissionMatrixCreate(PermissionMatrixBase):
    pass


class PermissionMatrixResponse(PermissionMatrixBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PermissionSnapshotBase(BaseModel):
    user_id: int
    system_code: str = Field(..., max_length=50)
    snapshot_date: date
    permissions: dict
    sync_source: Optional[str] = None


class PermissionSnapshotCreate(PermissionSnapshotBase):
    pass


class PermissionSnapshotResponse(PermissionSnapshotBase):
    id: int
    is_processed: bool
    created_at: datetime

    class Config:
        from_attributes = True


class PermissionDeviationBase(BaseModel):
    user_id: int
    system_code: str = Field(..., max_length=50)
    permission_code: str = Field(..., max_length=200)
    permission_name: str = Field(..., max_length=200)
    deviation_type: str = Field(..., max_length=20)
    standard_value: bool = False
    actual_value: bool = False


class PermissionDeviationResponse(PermissionDeviationBase):
    id: int
    snapshot_id: int
    risk_score: float
    risk_level: str
    status: str
    description: Optional[str]
    resolved_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AuditTicketBase(BaseModel):
    title: str = Field(..., max_length=500)
    deviation_id: int


class AuditTicketCreate(AuditTicketBase):
    pass


class AuditTicketUpdate(BaseModel):
    status: Optional[str] = None
    assignee_id: Optional[int] = None
    remarks: Optional[str] = None
    resolution: Optional[str] = None
    action_type: Optional[str] = None


class AuditTicketResponse(AuditTicketBase):
    id: int
    ticket_no: str
    status: str
    priority: str
    escalated: bool
    escalated_at: Optional[datetime]
    escalated_to: Optional[int]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class PermissionChangeHistoryResponse(BaseModel):
    id: int
    user_id: int
    system_code: str
    permission_code: str
    change_type: str
    old_value: bool
    new_value: bool
    operator: Optional[str]
    change_reason: Optional[str]
    source: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class AuditLogResponse(BaseModel):
    id: int
    user_id: Optional[int]
    username: Optional[str]
    action: str
    action_type: Optional[str]
    target_type: Optional[str]
    target_id: Optional[int]
    details: Optional[str]
    ip_address: Optional[str]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class ComplianceReportResponse(BaseModel):
    id: int
    report_date: date
    report_type: str
    total_deviations: int
    high_risk_count: int
    medium_risk_count: int
    low_risk_count: int
    resolved_count: int
    pending_count: int
    avg_fix_hours: float
    audit_completion_rate: float
    system_stats: Optional[dict]
    pdf_path: Optional[str]
    excel_path: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class SpecialAuditBase(BaseModel):
    title: str = Field(..., max_length=500)
    audit_type: str = "manual"
    target_user_ids: Optional[List[int]] = None
    target_system_codes: Optional[List[str]] = None


class SpecialAuditCreate(SpecialAuditBase):
    pass


class SpecialAuditResponse(SpecialAuditBase):
    id: int
    audit_no: str
    initiator_id: Optional[int]
    status: str
    result_summary: Optional[str]
    started_at: datetime
    completed_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class SyncRequest(BaseModel):
    system_code: Optional[str] = None
    user_ids: Optional[List[int]] = None


class DeviationListQuery(BaseModel):
    system_code: Optional[str] = None
    risk_level: Optional[str] = None
    status: Optional[str] = None
    user_id: Optional[int] = None
    page: int = 1
    page_size: int = 20


class TicketListQuery(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    assignee_id: Optional[int] = None
    escalated: Optional[bool] = None
    page: int = 1
    page_size: int = 20


class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[Any]
