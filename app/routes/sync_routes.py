from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.schemas import (
    PaginatedResponse, SyncRequest,
)
from app.services import (
    SnapshotSyncService,
    DeviationDetectionService,
    CRUDService,
)
from app.utils import logger, get_system_name

router = APIRouter(prefix="/api/v1/sync", tags=["权限同步与偏离检测"])


@router.post("/snapshot", summary="手动触发权限快照同步")
def sync_snapshots(
    req: Optional[SyncRequest] = None,
    db: Session = Depends(get_db),
):
    system_code = req.system_code if req else None
    user_ids = req.user_ids if req else None
    try:
        result = SnapshotSyncService.sync_all_users(
            db, system_code=system_code, user_ids=user_ids, trigger_by="manual_api"
        )
        return {"success": True, "data": result, "message": "同步完成"}
    except Exception as e:
        logger.error(f"手动同步失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")


@router.post("/snapshot/user/{user_id}", summary="同步指定用户的权限快照")
def sync_user_snapshot(
    user_id: int,
    system_code: Optional[str] = None,
    db: Session = Depends(get_db),
):
    from app.models import User
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    try:
        if system_code:
            snapshot = SnapshotSyncService.sync_user_system_snapshot(
                db, user, system_code, trigger_by="manual_api"
            )
            count = 1 if snapshot else 0
        else:
            snapshots = SnapshotSyncService.sync_all_systems_for_user(
                db, user, trigger_by="manual_api"
            )
            count = len(snapshots)
        return {"success": True, "data": {"snapshots": count}, "message": f"同步完成，共{count}个快照"}
    except Exception as e:
        logger.error(f"用户同步失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")


@router.post("/detect", summary="执行偏离检测（处理所有未处理快照）")
def run_detection(db: Session = Depends(get_db)):
    try:
        result = DeviationDetectionService.process_all_unprocessed(db)
        return {"success": True, "data": result, "message": "检测完成"}
    except Exception as e:
        logger.error(f"偏离检测失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"检测失败: {str(e)}")


@router.get("/snapshots", summary="权限快照列表")
def list_snapshots(
    user_id: Optional[int] = None,
    system_code: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items, total = CRUDService.list_snapshots(db, user_id, system_code, page, page_size)
    result_items = []
    for item in items:
        d = {
            "id": item.id,
            "user_id": item.user_id,
            "system_code": item.system_code,
            "system_name": get_system_name(item.system_code),
            "snapshot_date": item.snapshot_date,
            "permissions_count": len(item.permissions) if item.permissions else 0,
            "sync_source": item.sync_source,
            "is_processed": item.is_processed,
            "created_at": item.created_at,
        }
        result_items.append(d)
    return {"total": total, "page": page, "page_size": page_size, "items": result_items}


@router.get("/deviations", summary="权限偏离列表")
def list_deviations(
    user_id: Optional[int] = None,
    system_code: Optional[str] = None,
    risk_level: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items, total = CRUDService.list_deviations(db, user_id, system_code, risk_level, status, page, page_size)
    from app.utils import get_deviation_type_text, get_risk_level_text, get_status_text
    from app.models import User
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
            "permission_name": item.permission_name,
            "deviation_type": item.deviation_type,
            "deviation_type_text": get_deviation_type_text(item.deviation_type),
            "standard_value": item.standard_value,
            "actual_value": item.actual_value,
            "risk_score": item.risk_score,
            "risk_level": item.risk_level,
            "risk_level_text": get_risk_level_text(item.risk_level),
            "status": item.status,
            "status_text": get_status_text(item.status),
            "description": item.description,
            "created_at": item.created_at,
            "resolved_at": item.resolved_at,
        }
        result_items.append(d)
    return {"total": total, "page": page, "page_size": page_size, "items": result_items}


@router.get("/statistics", summary="偏离统计总览")
def get_deviation_statistics(db: Session = Depends(get_db)):
    stats = DeviationDetectionService.get_deviation_statistics(db)
    return {"success": True, "data": stats}
