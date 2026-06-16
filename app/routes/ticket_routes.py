from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.schemas import (
    AuditTicketCreate, AuditTicketUpdate, AuditTicketResponse,
    PaginatedResponse,
)
from app.services import TicketService, CRUDService
from app.utils import logger, get_risk_level_text, get_status_text, get_system_name
from app.models import User, AuditTicket, PermissionDeviation

router = APIRouter(prefix="/api/v1/tickets", tags=["审计工单管理"])


@router.post("/auto-generate", summary="自动生成审计工单（所有高风险未处理偏离）")
def auto_generate_tickets(db: Session = Depends(get_db)):
    tickets = TicketService.auto_generate_tickets(db)
    return {"success": True, "count": len(tickets), "message": f"生成{len(tickets)}个工单"}


@router.post("/check-upgrade", summary="检查并执行工单超时升级")
def check_ticket_upgrade(db: Session = Depends(get_db)):
    upgraded = TicketService.check_and_upgrade_tickets(db)
    return {"success": True, "count": len(upgraded), "message": f"升级{len(upgraded)}个工单"}


@router.put("/{ticket_id}/assign", summary="分配工单")
def assign_ticket(
    ticket_id: int,
    assignee_id: int,
    db: Session = Depends(get_db),
):
    ticket = TicketService.assign_ticket(db, ticket_id, assignee_id, operator_name="admin")
    if not ticket:
        raise HTTPException(status_code=404, detail="工单或处理人不存在")
    return {"success": True, "message": "分配成功", "data": {"ticket_no": ticket.ticket_no}}


@router.put("/{ticket_id}/resolve", summary="处理并关闭工单")
def resolve_ticket(
    ticket_id: int,
    resolution: str,
    action_type: str = Query(..., description="处理方式: adjust_permission/update_risk/confirm_ignore"),
    remarks: Optional[str] = None,
    db: Session = Depends(get_db),
):
    ticket = db.query(AuditTicket).get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")

    resolver_id = 1
    resolver_name = "admin"

    resolved = TicketService.resolve_ticket(
        db, ticket_id, resolution, action_type, resolver_id, resolver_name, remarks
    )
    if not resolved:
        raise HTTPException(status_code=500, detail="处理工单失败")
    return {"success": True, "message": "工单已解决", "data": {"ticket_no": resolved.ticket_no}}


@router.get("/", summary="工单列表")
def list_tickets(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assignee_id: Optional[int] = None,
    escalated: Optional[bool] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items, total = TicketService.get_tickets(db, status, priority, assignee_id, escalated, page, page_size)
    result_items = []
    for item in items:
        assignee = db.query(User).get(item.assignee_id)
        deviation = db.query(PermissionDeviation).get(item.deviation_id)
        escalated_to = db.query(User).get(item.escalated_to) if item.escalated_to else None
        d = {
            "id": item.id,
            "ticket_no": item.ticket_no,
            "title": item.title,
            "status": item.status,
            "status_text": get_status_text(item.status),
            "priority": item.priority,
            "priority_text": {"critical": "紧急", "urgent": "高", "high": "中", "normal": "低", "low": "极低"}.get(item.priority, item.priority),
            "assignee_id": item.assignee_id,
            "assignee_name": assignee.full_name if assignee else "未分配",
            "deviation_id": item.deviation_id,
            "escalated": item.escalated,
            "escalated_at": item.escalated_at,
            "escalated_to_name": escalated_to.full_name if escalated_to else None,
            "remarks": item.remarks,
            "resolution": item.resolution,
            "action_type": item.action_type,
            "resolved_at": item.resolved_at,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "risk_level_text": get_risk_level_text(deviation.risk_level) if deviation else None,
            "system_name": get_system_name(deviation.system_code) if deviation else None,
        }
        result_items.append(d)
    return {"total": total, "page": page, "page_size": page_size, "items": result_items}


@router.get("/{ticket_id}", summary="工单详情")
def get_ticket(ticket_id: int, db: Session = Depends(get_db)):
    ticket = db.query(AuditTicket).get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")

    assignee = db.query(User).get(ticket.assignee_id)
    deviation = db.query(PermissionDeviation).get(ticket.deviation_id)
    user = db.query(User).get(deviation.user_id) if deviation else None

    return {
        "id": ticket.id,
        "ticket_no": ticket.ticket_no,
        "title": ticket.title,
        "status": ticket.status,
        "status_text": get_status_text(ticket.status),
        "priority": ticket.priority,
        "assignee": assignee.full_name if assignee else None,
        "escalated": ticket.escalated,
        "escalated_at": ticket.escalated_at,
        "remarks": ticket.remarks,
        "resolution": ticket.resolution,
        "resolved_at": ticket.resolved_at,
        "created_at": ticket.created_at,
        "deviation": {
            "id": deviation.id if deviation else None,
            "username": user.username if user else None,
            "full_name": user.full_name if user else None,
            "system_code": deviation.system_code if deviation else None,
            "system_name": get_system_name(deviation.system_code) if deviation else None,
            "permission_name": deviation.permission_name if deviation else None,
            "deviation_type_text": get_risk_level_text(deviation.deviation_type) if deviation else None,
            "risk_score": deviation.risk_score if deviation else None,
            "risk_level": deviation.risk_level if deviation else None,
            "risk_level_text": get_risk_level_text(deviation.risk_level) if deviation else None,
            "description": deviation.description if deviation else None,
        } if deviation else None,
    }


@router.get("/statistics/summary", summary="工单统计")
def get_ticket_statistics(db: Session = Depends(get_db)):
    stats = TicketService.get_ticket_statistics(db)
    return {"success": True, "data": stats}
