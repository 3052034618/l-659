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
        if result["all_success"]:
            message = f"同步完成，共成功{result['total_snapshots']}个快照"
        elif result["total_snapshots"] > 0:
            message = f"同步部分完成，成功{result['total_snapshots']}个快照，失败{result['failed_users']}个用户"
        else:
            message = f"同步失败，{result['failed_users']}个用户全部同步失败"
        return {"success": result["total_snapshots"] > 0, "data": result, "message": message}
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
        failed_items = []
        if system_code:
            snapshot, message = SnapshotSyncService.sync_user_system_snapshot(
                db, user, system_code, trigger_by="manual_api"
            )
            count = 1 if snapshot else 0
            if not snapshot:
                from app.core.config import settings
                sys_info = next((s for s in settings.BUSINESS_SYSTEMS if s["code"] == system_code), None)
                failed_items.append({
                    "system_code": system_code,
                    "system_name": sys_info["name"] if sys_info else system_code,
                    "reason": message,
                })
        else:
            snapshots = SnapshotSyncService.sync_all_systems_for_user(
                db, user, trigger_by="manual_api"
            )
            count = len(snapshots)

        success = count > 0
        if success and not failed_items:
            msg = f"同步完成，共{count}个快照"
        elif success:
            msg = f"同步部分完成，成功{count}个快照，部分系统失败"
        else:
            msg = f"同步失败：{message if system_code else '所有系统同步失败'}"

        data = {
            "snapshots": count,
            "failed_items": failed_items,
        }
        return {"success": success, "data": data, "message": msg}
    except Exception as e:
        logger.error(f"用户同步失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")


@router.post("/detect", summary="执行偏离检测（处理所有未处理快照）")
def run_detection(db: Session = Depends(get_db)):
    try:
        result = DeviationDetectionService.process_all_unprocessed(db)
        message = (
            f"检测完成，共处理{result['processed_snapshots']}个快照，"
            f"发现{result['total_deviations']}项偏离（高危{result['high_risk_count']}项），"
            f"自动生成{result['new_ticket_count']}个工单"
        )
        return {"success": True, "data": result, "message": message}
    except Exception as e:
        logger.error(f"偏离检测失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"检测失败: {str(e)}")


@router.post("/sync_and_detect", summary="一键同步+检测+开工单（专项审计用）")
def sync_and_detect(
    req: Optional[SyncRequest] = None,
    db: Session = Depends(get_db),
):
    system_code = req.system_code if req else None
    user_ids = req.user_ids if req else None
    try:
        sync_result = SnapshotSyncService.sync_all_users(
            db, system_code=system_code, user_ids=user_ids, trigger_by="manual_api"
        )

        detect_result = DeviationDetectionService.process_all_unprocessed(db)

        combined = {
            "sync": sync_result,
            "detection": detect_result,
            "summary": {
                "success_snapshots": sync_result["total_snapshots"],
                "failed_snapshots": sync_result["failed_users"],
                "total_deviations": detect_result["total_deviations"],
                "high_risk_deviations": detect_result["high_risk_count"],
                "new_tickets": detect_result["new_ticket_count"],
            }
        }

        success_count = sync_result["total_snapshots"]
        if success_count == 0:
            msg = "同步全部失败，未执行检测"
        else:
            msg = (
                f"同步完成{success_count}个快照，"
                f"检测发现{detect_result['total_deviations']}项偏离"
                f"（高危{detect_result['high_risk_count']}项），"
                f"自动生成{detect_result['new_ticket_count']}个工单"
            )

        return {"success": success_count > 0, "data": combined, "message": msg}
    except Exception as e:
        logger.error(f"同步检测失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"操作失败: {str(e)}")


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
    from app.utils import deviation_to_dict, get_system_name
    from app.models import User
    result_items = []
    for item in items:
        dev_dict = deviation_to_dict(item)
        user = db.query(User).get(item.user_id)
        dev_dict["username"] = user.username if user else "-"
        dev_dict["full_name"] = user.full_name if user else "-"
        dev_dict["system_name"] = get_system_name(item.system_code)
        result_items.append(dev_dict)
    return {"total": total, "page": page, "page_size": page_size, "items": result_items}


@router.get("/statistics", summary="偏离统计总览")
def get_deviation_statistics(db: Session = Depends(get_db)):
    stats = DeviationDetectionService.get_deviation_statistics(db)
    return {"success": True, "data": stats}
