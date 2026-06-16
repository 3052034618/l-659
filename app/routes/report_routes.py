from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from datetime import date
from typing import Optional
import os

from app.core.database import get_db
from app.core.config import settings
from app.schemas import (
    ComplianceReportResponse, PaginatedResponse,
)
from app.services import ReportService, SchedulerService
from app.utils import logger

router = APIRouter(prefix="/api/v1/reports", tags=["合规报告与任务调度"])


@router.post("/daily/generate", summary="手动生成每日合规报告")
def generate_daily_report(
    report_date: Optional[date] = Query(None, description="报告日期，默认为今天"),
    db: Session = Depends(get_db),
):
    try:
        report = ReportService.generate_daily_report(db, report_date, operator_name="manual_api")
        return {
            "success": True,
            "message": "报告生成成功",
            "data": {
                "id": report.id,
                "report_date": report.report_date,
                "total_deviations": report.total_deviations,
                "audit_completion_rate": report.audit_completion_rate,
                "pdf_path": report.pdf_path,
                "excel_path": report.excel_path,
            }
        }
    except Exception as e:
        logger.error(f"生成报告失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"生成报告失败: {str(e)}")


@router.get("/daily", summary="合规报告列表")
def list_reports(
    report_type: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items, total = ReportService.get_reports(db, report_type, start_date, end_date, page, page_size)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/{report_id}", summary="报告详情")
def get_report(report_id: int, db: Session = Depends(get_db)):
    from app.models import ComplianceReport
    report = db.query(ComplianceReport).get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    return report


@router.get("/download/pdf/{report_id}", summary="下载PDF报告")
def download_pdf_report(report_id: int, db: Session = Depends(get_db)):
    from app.models import ComplianceReport
    report = db.query(ComplianceReport).get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")

    filepath = report.pdf_path
    if not filepath or not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="PDF文件不存在")

    filename = os.path.basename(filepath)
    return FileResponse(
        filepath,
        media_type="application/pdf",
        filename=filename,
    )


@router.get("/download/excel/{report_id}", summary="下载Excel报告")
def download_excel_report(report_id: int, db: Session = Depends(get_db)):
    from app.models import ComplianceReport
    report = db.query(ComplianceReport).get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")

    filepath = report.excel_path
    if not filepath or not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Excel文件不存在")

    filename = os.path.basename(filepath)
    return FileResponse(
        filepath,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )


@router.get("/scheduler/jobs", summary="获取所有定时任务")
def list_scheduled_jobs():
    jobs = SchedulerService.list_jobs()
    return {"success": True, "data": jobs}


@router.post("/scheduler/trigger/{job_id}", summary="手动触发定时任务")
def trigger_job(job_id: str):
    result = SchedulerService.trigger_job(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"success": True, "message": f"任务 {job_id} 已触发，将在下次调度时立即执行"}


@router.post("/scheduler/run/{task_name}", summary="立即执行指定任务")
def run_task_now(task_name: str):
    result = SchedulerService.run_task_immediately(task_name)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"任务 {task_name} 不存在，可选: sync, report, upgrade_check")
    return {"success": True, "data": result}


@router.get("/dashboard/overview", summary="仪表盘总览数据")
def dashboard_overview(db: Session = Depends(get_db)):
    from app.services.deviation_service import DeviationDetectionService
    from app.services.ticket_service import TicketService
    from app.models import User, PermissionSnapshot, PermissionDeviation, AuditTicket, SpecialAudit
    from datetime import datetime, timedelta

    deviation_stats = DeviationDetectionService.get_deviation_statistics(db)
    ticket_stats = TicketService.get_ticket_statistics(db)

    today = date.today()
    week_ago = datetime.now() - timedelta(days=7)
    month_ago = datetime.now() - timedelta(days=30)

    new_this_week = db.query(PermissionDeviation).filter(
        PermissionDeviation.created_at >= week_ago
    ).count()

    new_this_month = db.query(PermissionDeviation).filter(
        PermissionDeviation.created_at >= month_ago
    ).count()

    return {
        "success": True,
        "data": {
            "users_count": db.query(User).count(),
            "snapshots_count": db.query(PermissionSnapshot).count(),
            "deviations": deviation_stats,
            "tickets": ticket_stats,
            "new_this_week": new_this_week,
            "new_this_month": new_this_month,
            "special_audits_count": db.query(SpecialAudit).count(),
            "pending_high_risk": db.query(PermissionDeviation).filter(
                PermissionDeviation.risk_level == "high",
                PermissionDeviation.status.in_(["pending", "processing"]),
            ).count(),
        }
    }
