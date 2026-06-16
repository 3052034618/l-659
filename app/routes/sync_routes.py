from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List

from app.core.database import get_db
from app.schemas import (
    PaginatedResponse, SyncRequest,
)
from app.services import (
    SnapshotSyncService,
    DeviationDetectionService,
    CRUDService,
    AuditBatchService,
)
from app.utils import logger, get_system_name

router = APIRouter(prefix="/api/v1/sync", tags=["权限同步与偏离检测"])


class SyncSnapshotRequest(BaseModel):
    system_code: Optional[str] = None
    user_ids: Optional[List[int]] = None
    force_refresh: bool = False


@router.post("/snapshot", summary="手动触发权限快照同步")
def sync_snapshots(
    req: Optional[SyncSnapshotRequest] = None,
    db: Session = Depends(get_db),
):
    system_code = req.system_code if req else None
    user_ids = req.user_ids if req else None
    force_refresh = req.force_refresh if req else False
    try:
        result = SnapshotSyncService.sync_all_users(
            db,
            system_code=system_code,
            user_ids=user_ids,
            trigger_by="manual_api",
            force_refresh=force_refresh,
        )
        success_snapshots = result.get("success_snapshots", 0)
        skipped_snapshots = result.get("skipped_snapshots", 0)
        failed_snapshots = result.get("failed_snapshots", 0)
        total = success_snapshots + skipped_snapshots + failed_snapshots

        if result["all_success"] and failed_snapshots == 0:
            message = f"同步完成，共成功{success_snapshots}个快照"
            if skipped_snapshots > 0:
                message += f"（复用已有快照{skipped_snapshots}个）"
        elif success_snapshots > 0 or skipped_snapshots > 0:
            message = f"同步部分完成，成功{success_snapshots}个，复用{skipped_snapshots}个，失败{failed_snapshots}个"
        else:
            message = f"同步失败，{failed_snapshots}个系统全部同步失败"
        return {"success": success_snapshots > 0 or skipped_snapshots > 0, "data": result, "message": message}
    except Exception as e:
        logger.error(f"手动同步失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")


@router.post("/snapshot/user/{user_id}", summary="同步指定用户的权限快照")
def sync_user_snapshot(
    user_id: int,
    system_code: Optional[str] = None,
    force_refresh: bool = Query(False, description="是否强制刷新，删除已有快照重新同步"),
    db: Session = Depends(get_db),
):
    from app.models import User
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    try:
        if system_code:
            snapshot, message, status = SnapshotSyncService.sync_user_system_snapshot(
                db, user, system_code, trigger_by="manual_api", force_refresh=force_refresh
            )
            success_count = 1 if status == "success" else 0
            skipped_count = 1 if status == "skipped" else 0
            failed_count = 1 if status == "failed" else 0

            failed_systems = []
            skipped_systems = []
            if status == "failed":
                from app.core.config import settings
                sys_info = next((s for s in settings.BUSINESS_SYSTEMS if s["code"] == system_code), None)
                failed_systems.append({
                    "system_code": system_code,
                    "system_name": sys_info["name"] if sys_info else system_code,
                    "reason": message,
                })
            elif status == "skipped":
                from app.core.config import settings
                sys_info = next((s for s in settings.BUSINESS_SYSTEMS if s["code"] == system_code), None)
                skipped_systems.append({
                    "system_code": system_code,
                    "system_name": sys_info["name"] if sys_info else system_code,
                    "reason": message,
                })
        else:
            sync_result = SnapshotSyncService.sync_all_systems_for_user(
                db, user, trigger_by="manual_api", force_refresh=force_refresh
            )
            success_count = sync_result["success_snapshots"]
            skipped_count = sync_result["skipped_snapshots"]
            failed_count = sync_result["failed_snapshots"]
            failed_systems = sync_result["failed_systems"]
            skipped_systems = sync_result["skipped_systems"]

        success = success_count > 0 or skipped_count > 0
        if success and failed_count == 0:
            msg = f"同步完成，成功{success_count}个，复用{skipped_count}个，共{success_count + skipped_count}个快照"
        elif success:
            msg = f"同步部分完成，成功{success_count}个，复用{skipped_count}个，失败{failed_count}个"
        else:
            msg = f"同步失败：{failed_count}个系统全部失败"

        data = {
            "success_snapshots": success_count,
            "skipped_snapshots": skipped_count,
            "failed_snapshots": failed_count,
            "total_snapshots": success_count + skipped_count + failed_count,
            "failed_systems": failed_systems,
            "skipped_systems": skipped_systems,
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
    req: Optional[SyncSnapshotRequest] = None,
    db: Session = Depends(get_db),
):
    system_code = req.system_code if req else None
    user_ids = req.user_ids if req else None
    force_refresh = req.force_refresh if req else False
    try:
        sync_result = SnapshotSyncService.sync_all_users(
            db,
            system_code=system_code,
            user_ids=user_ids,
            trigger_by="manual_api",
            force_refresh=force_refresh,
        )

        success_snapshots = sync_result.get("success_snapshots", 0)
        new_snapshot_ids = sync_result.get("new_snapshot_ids", [])

        detect_result = {
            "processed_snapshots": 0,
            "total_deviations": 0,
            "high_risk_count": 0,
            "new_ticket_count": 0,
            "skipped_reason": "",
        }

        if success_snapshots == 0 and len(new_snapshot_ids) == 0:
            detect_result["skipped_reason"] = "本次未获取到任何新的权限快照，已跳过偏离检测"
        else:
            detect_result = DeviationDetectionService.process_snapshots_with_batch(
                db, snapshot_ids=new_snapshot_ids
            )
            from app.services import TicketService
            new_tickets = TicketService.auto_generate_tickets(
                db,
                deviation_ids=[d.id for d in detect_result.get("deviations", [])],
            )
            detect_result["new_ticket_count"] = len(new_tickets)

        combined = {
            "sync": sync_result,
            "detection": detect_result,
            "summary": {
                "success_snapshots": sync_result.get("success_snapshots", 0),
                "skipped_snapshots": sync_result.get("skipped_snapshots", 0),
                "failed_snapshots": sync_result.get("failed_snapshots", 0),
                "total_deviations": detect_result["total_deviations"],
                "high_risk_deviations": detect_result["high_risk_count"],
                "new_tickets": detect_result["new_ticket_count"],
            }
        }

        if success_snapshots == 0 and len(new_snapshot_ids) == 0:
            msg = "同步全部失败或无新快照，已跳过偏离检测和工单生成"
            success = False
        else:
            msg = (
                f"同步完成{sync_result.get('success_snapshots', 0)}个（复用{sync_result.get('skipped_snapshots', 0)}个，失败{sync_result.get('failed_snapshots', 0)}个），"
                f"检测发现{detect_result['total_deviations']}项偏离"
                f"（高危{detect_result['high_risk_count']}项），"
                f"自动生成{detect_result['new_ticket_count']}个工单"
            )
            success = True

        return {"success": success, "data": combined, "message": msg}
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
