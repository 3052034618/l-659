from datetime import datetime, date
from typing import Dict, List, Optional, Tuple
from sqlalchemy import and_
from sqlalchemy.orm import Session
import uuid
import json
import os
import zipfile
import io

from app.models import (
    SpecialAudit,
    PermissionSnapshot,
    PermissionDeviation,
    AuditTicket,
    PermissionChangeHistory,
    User,
)
from app.core.config import settings
from app.utils import get_risk_level_text, get_deviation_type_text, get_system_name, log_audit
from app.services import SnapshotSyncService, DeviationDetectionService, TicketService

import logging
logger = logging.getLogger(__name__)


class AuditBatchService:
    @staticmethod
    def generate_batch_no() -> str:
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        suffix = uuid.uuid4().hex[:6].upper()
        return f"AUDIT-{ts}-{suffix}"

    @classmethod
    def create_batch(
        cls,
        db: Session,
        title: str,
        target_user_ids: Optional[List[int]] = None,
        target_system_codes: Optional[List[str]] = None,
        initiator_id: Optional[int] = None,
        initiator_name: str = "system",
    ) -> SpecialAudit:
        batch_no = cls.generate_batch_no()
        audit_no = f"SA-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"

        batch = SpecialAudit(
            batch_no=batch_no,
            audit_no=audit_no,
            title=title,
            audit_type="manual",
            target_user_ids=target_user_ids if target_user_ids else None,
            target_system_codes=target_system_codes if target_system_codes else None,
            initiator_id=initiator_id,
            status="syncing",
            started_at=datetime.now(),
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)

        log_audit(
            db=db,
            action="create_audit_batch",
            action_type="audit",
            target_type="audit_batch",
            target_id=batch.id,
            details=f"创建专项审计批次: {batch_no}，目标: 用户{len(target_user_ids or [])}个，系统{len(target_system_codes or [])}个",
            username=initiator_name,
            status="success",
        )
        logger.info(f"已创建审计批次 {batch_no}")
        return batch

    @classmethod
    def run_full_audit(
        cls,
        db: Session,
        batch: SpecialAudit,
        force_refresh: bool = False,
        initiator_name: str = "system",
    ) -> Dict:
        batch_no = batch.batch_no
        target_user_ids = batch.target_user_ids
        target_system_codes = batch.target_system_codes

        # ---------------- 1. 同步权限快照 ----------------
        batch.status = "syncing"
        db.commit()

        sync_result = SnapshotSyncService.sync_all_users_with_batch(
            db=db,
            audit_batch_id=batch.id,
            system_code=None,
            user_ids=target_user_ids,
            system_codes=target_system_codes,
            trigger_by=f"audit_batch:{batch_no}",
            force_refresh=force_refresh,
        )

        success_snapshots = sync_result.get("success_snapshots", 0)
        skipped_snapshots = sync_result.get("skipped_snapshots", 0)
        failed_snapshots = sync_result.get("failed_snapshots", 0)
        new_snapshot_ids = sync_result.get("new_snapshot_ids", [])
        failed_items = sync_result.get("failed_items", [])

        logger.info(f"批次[{batch_no}]同步完成: 成功{success_snapshots}, 跳过{skipped_snapshots}, 失败{failed_snapshots}")

        # ---------------- 2. 偏离检测（只处理本次新拿到的快照） ----------------
        detect_result = {
            "processed_snapshots": 0,
            "total_deviations": 0,
            "high_risk_count": 0,
            "medium_risk_count": 0,
            "low_risk_count": 0,
            "new_ticket_count": 0,
            "skipped_reason": "",
        }

        if success_snapshots == 0 and len(new_snapshot_ids) == 0:
            detect_result["skipped_reason"] = "本次未获取到任何有效的权限快照，已跳过偏离检测"
            logger.warning(f"批次[{batch_no}]同步全部失败，跳过偏离检测")
        else:
            batch.status = "detecting"
            db.commit()

            detect_result = DeviationDetectionService.process_snapshots_with_batch(
                db=db,
                snapshot_ids=new_snapshot_ids,
                audit_batch_id=batch.id,
            )

            # ---------------- 3. 自动生成工单 ----------------
            batch.status = "ticketing"
            db.commit()

            new_tickets = TicketService.auto_generate_tickets(
                db=db,
                audit_batch_id=batch.id,
                deviation_ids=[d.id for d in detect_result.get("deviations", [])],
            )
            detect_result["new_ticket_count"] = len(new_tickets)

        # ---------------- 4. 更新批次状态 ----------------
        batch.status = "completed"
        batch.completed_at = datetime.now()
        total_count = detect_result["total_deviations"]
        high_count = detect_result["high_risk_count"]
        ticket_count = detect_result["new_ticket_count"]
        batch.result_summary = (
            f"同步完成{success_snapshots}个快照（跳过{skipped_snapshots}个，失败{failed_snapshots}个），"
            f"检测发现{total_count}项偏离（高危{high_count}项），自动生成{ticket_count}个工单"
        )
        db.commit()
        db.refresh(batch)

        log_audit(
            db=db,
            action="complete_audit_batch",
            action_type="audit",
            target_type="audit_batch",
            target_id=batch.id,
            details=batch.result_summary,
            username=initiator_name,
            status="success",
        )

        # ---------------- 5. 返回整合结果 ----------------
        return {
            "batch_no": batch_no,
            "audit_no": batch.audit_no,
            "status": batch.status,
            "sync": {
                "success_snapshots": success_snapshots,
                "skipped_snapshots": skipped_snapshots,
                "failed_snapshots": failed_snapshots,
                "total_snapshots": success_snapshots + skipped_snapshots + failed_snapshots,
                "failed_items": failed_items,
            },
            "detection": {
                "processed_snapshots": detect_result["processed_snapshots"],
                "total_deviations": detect_result["total_deviations"],
                "high_risk_count": detect_result["high_risk_count"],
                "medium_risk_count": detect_result.get("medium_risk_count", 0),
                "low_risk_count": detect_result.get("low_risk_count", 0),
                "new_ticket_count": detect_result["new_ticket_count"],
                "skipped_reason": detect_result.get("skipped_reason", ""),
            },
            "summary": {
                "success_snapshots": success_snapshots,
                "skipped_snapshots": skipped_snapshots,
                "failed_snapshots": failed_snapshots,
                "total_deviations": total_count,
                "high_risk_deviations": high_count,
                "new_tickets": ticket_count,
            }
        }

    @classmethod
    def get_batch_detail(cls, db: Session, batch_no: str) -> Optional[Dict]:
        batch = db.query(SpecialAudit).filter(SpecialAudit.batch_no == batch_no).first()
        if not batch:
            return None

        target_users = []
        if batch.target_user_ids:
            users = db.query(User).filter(User.id.in_(batch.target_user_ids)).all()
            target_users = [{"id": u.id, "username": u.username, "full_name": u.full_name} for u in users]

        target_systems = []
        if batch.target_system_codes:
            target_systems = [
                {"code": code, "name": get_system_name(code)}
                for code in batch.target_system_codes
            ]

        # 失败系统和原因
        failed_snapshots = db.query(PermissionSnapshot).filter(
            and_(
                PermissionSnapshot.audit_batch_id == batch.id,
                PermissionSnapshot.sync_status == "failed",
            )
        ).all()
        failed_systems = []
        for s in failed_snapshots:
            u = db.query(User).get(s.user_id)
            failed_systems.append({
                "user_id": s.user_id,
                "username": u.username if u else "",
                "full_name": u.full_name if u else "",
                "system_code": s.system_code,
                "system_name": get_system_name(s.system_code),
                "fail_reason": s.skip_reason or "未知原因",
            })

        # 高危偏离清单
        high_risk_deviations = db.query(PermissionDeviation).filter(
            and_(
                PermissionDeviation.audit_batch_id == batch.id,
                PermissionDeviation.risk_level == "high",
            )
        ).all()
        high_risk_list = []
        for d in high_risk_deviations:
            u = db.query(User).get(d.user_id)
            high_risk_list.append({
                "id": d.id,
                "user_id": d.user_id,
                "username": u.username if u else "",
                "full_name": u.full_name if u else "",
                "system_code": d.system_code,
                "system_name": get_system_name(d.system_code),
                "permission_code": d.permission_code,
                "permission_name": d.permission_name,
                "deviation_type": d.deviation_type,
                "deviation_type_text": get_deviation_type_text(d.deviation_type),
                "risk_score": d.risk_score,
                "risk_level": d.risk_level,
                "risk_level_text": get_risk_level_text(d.risk_level),
                "status": d.status,
            })

        # 工单列表及处理状态
        tickets = db.query(AuditTicket).filter(AuditTicket.audit_batch_id == batch.id).all()
        ticket_list = []
        for t in tickets:
            dev = db.query(PermissionDeviation).get(t.deviation_id)
            u = db.query(User).get(t.assignee_id)
            ticket_list.append({
                "id": t.id,
                "ticket_no": t.ticket_no,
                "title": t.title,
                "status": t.status,
                "assignee_id": t.assignee_id,
                "assignee_name": u.full_name if u else "",
                "priority": t.priority,
                "deviation_type_text": get_deviation_type_text(dev.deviation_type) if dev else "",
                "risk_level_text": get_risk_level_text(dev.risk_level) if dev else "",
                "created_at": t.created_at.isoformat() if t.created_at else "",
                "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
            })

        # 进度统计
        total_snapshots = db.query(PermissionSnapshot).filter(
            PermissionSnapshot.audit_batch_id == batch.id
        ).count()
        total_devs = db.query(PermissionDeviation).filter(
            PermissionDeviation.audit_batch_id == batch.id
        ).count()
        resolved_devs = db.query(PermissionDeviation).filter(
            and_(
                PermissionDeviation.audit_batch_id == batch.id,
                PermissionDeviation.status == "resolved",
            )
        ).count()
        total_tickets = len(tickets)
        resolved_tickets = len([t for t in tickets if t.status == "resolved"])

        change_histories = db.query(PermissionChangeHistory).filter(
            PermissionChangeHistory.audit_batch_id == batch.id
        ).count()

        return {
            "batch_no": batch.batch_no,
            "audit_no": batch.audit_no,
            "title": batch.title,
            "status": batch.status,
            "initiator_id": batch.initiator_id,
            "target_users": target_users,
            "target_systems": target_systems,
            "started_at": batch.started_at.isoformat() if batch.started_at else "",
            "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
            "result_summary": batch.result_summary,
            "progress": {
                "total_snapshots": total_snapshots,
                "failed_snapshots": len(failed_snapshots),
                "total_deviations": total_devs,
                "resolved_deviations": resolved_devs,
                "high_risk_deviations": len(high_risk_list),
                "total_tickets": total_tickets,
                "resolved_tickets": resolved_tickets,
                "change_histories": change_histories,
            },
            "failed_systems": failed_systems,
            "high_risk_deviations": high_risk_list,
            "tickets": ticket_list,
        }

    @classmethod
    def export_evidence_package(cls, db: Session, batch_no: str) -> Optional[Tuple[bytes, str]]:
        detail = cls.get_batch_detail(db, batch_no)
        if not detail:
            return None

        batch_id = db.query(SpecialAudit.id).filter(SpecialAudit.batch_no == batch_no).scalar()

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("00_审计批次信息.json", json.dumps(detail, ensure_ascii=False, indent=2))

            # 快照明细
            snapshots = db.query(PermissionSnapshot).filter(
                PermissionSnapshot.audit_batch_id == batch_id
            ).all()
            snapshot_data = []
            for s in snapshots:
                u = db.query(User).get(s.user_id)
                snapshot_data.append({
                    "snapshot_id": s.id,
                    "username": u.username if u else "",
                    "full_name": u.full_name if u else "",
                    "system_code": s.system_code,
                    "system_name": get_system_name(s.system_code),
                    "snapshot_date": s.snapshot_date.isoformat(),
                    "sync_status": s.sync_status,
                    "permissions": s.permissions,
                    "created_at": s.created_at.isoformat(),
                })
            zf.writestr("01_权限快照明细.json", json.dumps(snapshot_data, ensure_ascii=False, indent=2))

            # 偏离明细
            deviations = db.query(PermissionDeviation).filter(
                PermissionDeviation.audit_batch_id == batch_id
            ).all()
            deviation_data = []
            for d in deviations:
                u = db.query(User).get(d.user_id)
                deviation_data.append({
                    "deviation_id": d.id,
                    "username": u.username if u else "",
                    "full_name": u.full_name if u else "",
                    "system_code": d.system_code,
                    "system_name": get_system_name(d.system_code),
                    "permission_code": d.permission_code,
                    "permission_name": d.permission_name,
                    "deviation_type": d.deviation_type,
                    "deviation_type_text": get_deviation_type_text(d.deviation_type),
                    "standard_value": d.standard_value,
                    "actual_value": d.actual_value,
                    "risk_score": d.risk_score,
                    "risk_level": d.risk_level,
                    "risk_level_text": get_risk_level_text(d.risk_level),
                    "status": d.status,
                    "resolved_action": d.resolved_action,
                    "created_at": d.created_at.isoformat(),
                    "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None,
                })
            zf.writestr("02_权限偏离明细.json", json.dumps(deviation_data, ensure_ascii=False, indent=2))

            # 工单明细
            tickets = db.query(AuditTicket).filter(
                AuditTicket.audit_batch_id == batch_id
            ).all()
            ticket_data = []
            for t in tickets:
                dev = db.query(PermissionDeviation).get(t.deviation_id)
                u = db.query(User).get(t.assignee_id)
                ru = db.query(User).get(t.resolved_by)
                ticket_data.append({
                    "ticket_id": t.id,
                    "ticket_no": t.ticket_no,
                    "title": t.title,
                    "status": t.status,
                    "assignee": u.full_name if u else "",
                    "priority": t.priority,
                    "deviation_type": get_deviation_type_text(dev.deviation_type) if dev else "",
                    "risk_level": get_risk_level_text(dev.risk_level) if dev else "",
                    "action_type": t.action_type,
                    "resolution": t.resolution,
                    "resolved_by": ru.full_name if ru else "",
                    "created_at": t.created_at.isoformat(),
                    "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
                })
            zf.writestr("03_审计工单明细.json", json.dumps(ticket_data, ensure_ascii=False, indent=2))

            # 变更历史
            changes = db.query(PermissionChangeHistory).filter(
                PermissionChangeHistory.audit_batch_id == batch_id
            ).all()
            change_data = []
            for c in changes:
                u = db.query(User).get(c.user_id)
                change_data.append({
                    "change_id": c.id,
                    "username": u.username if u else "",
                    "full_name": u.full_name if u else "",
                    "system_code": c.system_code,
                    "system_name": get_system_name(c.system_code),
                    "permission_code": c.permission_code,
                    "change_type": "授予" if c.change_type == "grant" else "撤销",
                    "old_value": c.old_value,
                    "new_value": c.new_value,
                    "operator": c.operator,
                    "change_reason": c.change_reason,
                    "source": c.source,
                    "created_at": c.created_at.isoformat(),
                })
            zf.writestr("04_权限变更历史.json", json.dumps(change_data, ensure_ascii=False, indent=2))

            # 说明文档
            readme = f"""权限专项审计证据包
======================

批次号: {batch_no}
审计编号: {detail['audit_no']}
标题: {detail['title']}
开始时间: {detail['started_at']}
完成时间: {detail['completed_at']}

统计信息:
- 快照总数: {detail['progress']['total_snapshots']} (失败{detail['progress']['failed_snapshots']})
- 偏离总数: {detail['progress']['total_deviations']} (高危{detail['progress']['high_risk_deviations']})
- 工单总数: {detail['progress']['total_tickets']} (已解决{detail['progress']['resolved_tickets']})
- 变更记录: {detail['progress']['change_histories']} 条

文件说明:
00_审计批次信息.json  - 批次概要信息
01_权限快照明细.json  - 本次同步的所有权限快照
02_权限偏离明细.json  - 检测发现的所有权限偏离
03_审计工单明细.json  - 自动生成的审计工单
04_权限变更历史.json  - 本次审计产生的权限变更记录

生成时间: {datetime.now().isoformat()}
"""
            zf.writestr("README.txt", readme)

        buf.seek(0)
        filename = f"audit_evidence_{batch_no}_{datetime.now().strftime('%Y%m%d%H%M%S')}.zip"
        return buf.getvalue(), filename

    @classmethod
    def list_batches(cls, db: Session, skip: int = 0, limit: int = 20) -> Dict:
        query = db.query(SpecialAudit).order_by(SpecialAudit.created_at.desc())
        total = query.count()
        batches = query.offset(skip).limit(limit).all()

        items = []
        for b in batches:
            snap_count = len(b.snapshots)
            dev_count = len(b.deviations)
            high_count = len([d for d in b.deviations if d.risk_level == "high"])
            ticket_count = len(b.tickets)
            items.append({
                "id": b.id,
                "batch_no": b.batch_no,
                "audit_no": b.audit_no,
                "title": b.title,
                "status": b.status,
                "target_users_count": len(b.target_user_ids or []),
                "target_systems_count": len(b.target_system_codes or []),
                "snapshot_count": snap_count,
                "deviation_count": dev_count,
                "high_risk_count": high_count,
                "ticket_count": ticket_count,
                "started_at": b.started_at.isoformat() if b.started_at else "",
                "completed_at": b.completed_at.isoformat() if b.completed_at else None,
            })

        return {"total": total, "items": items}
