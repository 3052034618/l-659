from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List

from app.core.database import get_db
from app.schemas import (
    SpecialAuditCreate, SpecialAuditResponse,
    PaginatedResponse, PermissionChangeHistoryResponse,
)
from app.services import SpecialAuditService, ChangeHistoryService, CRUDService
from app.utils import logger, get_system_name
from app.models import User

router = APIRouter(prefix="/api/v1/audit", tags=["专项审计与变更历史"])


@router.post("/special", summary="发起专项审计")
def create_special_audit(
    data: SpecialAuditCreate,
    db: Session = Depends(get_db),
):
    try:
        audit = SpecialAuditService.create_audit(
            db,
            title=data.title,
            audit_type=data.audit_type,
            target_user_ids=data.target_user_ids,
            target_system_codes=data.target_system_codes,
            initiator_id=1,
            initiator_name="admin",
        )
        result = SpecialAuditService.run_audit(db, audit.id)
        return {"success": True, "message": "审计执行完成", "data": result}
    except Exception as e:
        logger.error(f"专项审计失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"审计失败: {str(e)}")


@router.post("/special/{audit_id}/run", summary="执行指定的专项审计")
def run_special_audit(audit_id: int, db: Session = Depends(get_db)):
    result = SpecialAuditService.run_audit(db, audit_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return {"success": True, "data": result}


@router.get("/special", summary="专项审计列表")
def list_special_audits(
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items, total = SpecialAuditService.get_audits(db, status, page, page_size)
    result_items = []
    for item in items:
        initiator = db.query(User).get(item.initiator_id)
        d = {
            "id": item.id,
            "audit_no": item.audit_no,
            "title": item.title,
            "audit_type": item.audit_type,
            "target_users_count": len(item.target_user_ids) if item.target_user_ids else 0,
            "target_systems_count": len(item.target_system_codes) if item.target_system_codes else 0,
            "initiator_name": initiator.full_name if initiator else None,
            "status": item.status,
            "status_text": {"running": "进行中", "completed": "已完成"}.get(item.status, item.status),
            "result_summary": item.result_summary,
            "started_at": item.started_at,
            "completed_at": item.completed_at,
            "created_at": item.created_at,
        }
        result_items.append(d)
    return {"total": total, "page": page, "page_size": page_size, "items": result_items}


@router.get("/special/{audit_id}", summary="专项审计详情")
def get_special_audit(audit_id: int, db: Session = Depends(get_db)):
    from app.models import SpecialAudit
    audit = db.query(SpecialAudit).get(audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="审计任务不存在")
    return SpecialAuditService.run_audit(db, audit_id)


@router.get("/history/user/{user_id}", summary="用户权限变更历史")
def get_user_change_history(
    user_id: int,
    system_code: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items, total = ChangeHistoryService.get_user_change_history(
        db, user_id, system_code, None, None, page, page_size
    )
    result_items = []
    for item in items:
        d = {
            "id": item.id,
            "user_id": item.user_id,
            "system_code": item.system_code,
            "system_name": get_system_name(item.system_code),
            "permission_code": item.permission_code,
            "change_type": item.change_type,
            "change_type_text": "授予权限" if item.change_type == "grant" else "撤销权限",
            "old_value": item.old_value,
            "new_value": item.new_value,
            "operator": item.operator,
            "change_reason": item.change_reason,
            "source": item.source,
            "created_at": item.created_at,
        }
        result_items.append(d)
    return {"total": total, "page": page, "page_size": page_size, "items": result_items}


@router.get("/history/system/{system_code}", summary="系统权限变更历史")
def get_system_change_history(
    system_code: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items, total = ChangeHistoryService.get_system_change_history(
        db, system_code, None, None, page, page_size
    )
    result_items = []
    for item in items:
        user = db.query(User).get(item.user_id)
        d = {
            "id": item.id,
            "user_id": item.user_id,
            "username": user.username if user else "-",
            "full_name": user.full_name if user else "-",
            "system_code": item.system_code,
            "system_name": get_system_name(item.system_code),
            "permission_code": item.permission_code,
            "change_type": item.change_type,
            "change_type_text": "授予权限" if item.change_type == "grant" else "撤销权限",
            "old_value": item.old_value,
            "new_value": item.new_value,
            "operator": item.operator,
            "change_reason": item.change_reason,
            "source": item.source,
            "created_at": item.created_at,
        }
        result_items.append(d)
    return {"total": total, "page": page, "page_size": page_size, "items": result_items}


@router.get("/history/summary", summary="变更历史统计汇总")
def get_change_summary(
    user_ids: Optional[str] = Query(None, description="用户ID，逗号分隔"),
    system_codes: Optional[str] = Query(None, description="系统编码，逗号分隔"),
    db: Session = Depends(get_db),
):
    uid_list = [int(x) for x in user_ids.split(",")] if user_ids else None
    sys_list = system_codes.split(",") if system_codes else None
    summary = ChangeHistoryService.summarize_changes(db, uid_list, sys_list)

    result = dict(summary)
    if "by_user" in result:
        user_map = {}
        for uid, cnt in result["by_user"].items():
            user = db.query(User).get(uid)
            user_map[user.full_name if user else f"#{uid}"] = cnt
        result["by_user"] = user_map
    if "by_system" in result:
        sys_map = {}
        for code, cnt in result["by_system"].items():
            sys_map[get_system_name(code)] = cnt
        result["by_system"] = sys_map

    return {"success": True, "data": result}


@router.get("/logs", summary="系统操作日志")
def list_audit_logs(
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    items, total = CRUDService.list_audit_logs(db, user_id, action, target_type, None, None, page, page_size)
    return {"total": total, "page": page, "page_size": page_size, "items": items}
