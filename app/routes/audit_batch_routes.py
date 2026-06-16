from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List

from app.core.database import get_db
from app.services import AuditBatchService

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/audit-batches", tags=["专项审计批次管理"])


class CreateAuditBatchRequest(BaseModel):
    title: str
    target_user_ids: Optional[List[int]] = None
    target_system_codes: Optional[List[str]] = None
    force_refresh: bool = False


@router.get("", summary="查询审计批次列表")
def list_audit_batches(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    skip = (page - 1) * page_size
    result = AuditBatchService.list_batches(db, skip=skip, limit=page_size)
    return {"success": True, "data": result}


@router.post("", summary="创建审计批次")
def create_audit_batch(
    req: CreateAuditBatchRequest,
    db: Session = Depends(get_db),
):
    try:
        batch = AuditBatchService.create_batch(
            db=db,
            title=req.title,
            target_user_ids=req.target_user_ids,
            target_system_codes=req.target_system_codes,
            initiator_name="manual_api",
        )
        return {
            "success": True,
            "message": "审计批次创建成功",
            "data": {
                "batch_id": batch.id,
                "batch_no": batch.batch_no,
                "audit_no": batch.audit_no,
                "title": batch.title,
                "status": batch.status,
            }
        }
    except Exception as e:
        logger.error(f"创建审计批次失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")


@router.post("/{batch_no}/run", summary="执行指定审计批次（同步+检测+开工单）")
def run_audit_batch(
    batch_no: str,
    force_refresh: bool = Query(False, description="是否强制刷新快照"),
    db: Session = Depends(get_db),
):
    from app.models import SpecialAudit
    batch = db.query(SpecialAudit).filter(SpecialAudit.batch_no == batch_no).first()
    if not batch:
        raise HTTPException(status_code=404, detail="审计批次不存在")

    try:
        result = AuditBatchService.run_full_audit(
            db=db,
            batch=batch,
            force_refresh=force_refresh,
            initiator_name="manual_api",
        )
        return {
            "success": True,
            "message": result.get("result_summary", "审计执行完成"),
            "data": result,
        }
    except Exception as e:
        logger.error(f"执行审计批次失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"执行失败: {str(e)}")


@router.post("/create-and-run", summary="创建并立即执行审计批次（专项审计一键完成）")
def create_and_run_audit_batch(
    req: CreateAuditBatchRequest,
    db: Session = Depends(get_db),
):
    try:
        batch = AuditBatchService.create_batch(
            db=db,
            title=req.title,
            target_user_ids=req.target_user_ids,
            target_system_codes=req.target_system_codes,
            initiator_name="manual_api",
        )

        result = AuditBatchService.run_full_audit(
            db=db,
            batch=batch,
            force_refresh=req.force_refresh,
            initiator_name="manual_api",
        )

        return {
            "success": True,
            "message": f"审计批次[{batch.batch_no}]执行完成",
            "data": result,
        }
    except Exception as e:
        logger.error(f"创建并执行审计批次失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"操作失败: {str(e)}")


@router.get("/{batch_no}", summary="查询审计批次详情（进度、失败原因、偏离、工单）")
def get_audit_batch_detail(
    batch_no: str,
    db: Session = Depends(get_db),
):
    detail = AuditBatchService.get_batch_detail(db, batch_no)
    if not detail:
        raise HTTPException(status_code=404, detail="审计批次不存在")
    return {"success": True, "data": detail}


@router.get("/{batch_no}/export", summary="导出审计证据包（ZIP格式）")
def export_audit_evidence(
    batch_no: str,
    db: Session = Depends(get_db),
):
    result = AuditBatchService.export_evidence_package(db, batch_no)
    if not result:
        raise HTTPException(status_code=404, detail="审计批次不存在")

    zip_content, filename = result
    return Response(
        content=zip_content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}"
        }
    )
