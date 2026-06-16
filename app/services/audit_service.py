from datetime import datetime
from typing import List, Optional, Dict, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from app.models import (
    SpecialAudit,
    PermissionChangeHistory,
    PermissionSnapshot,
    PermissionDeviation,
    User,
)
from app.utils import (
    logger,
    log_audit,
    generate_audit_no,
    get_deviation_type_text,
    get_risk_level_text,
    get_system_name,
)


class SpecialAuditService:
    @classmethod
    def create_audit(
        cls,
        db: Session,
        title: str,
        audit_type: str = "manual",
        target_user_ids: Optional[List[int]] = None,
        target_system_codes: Optional[List[str]] = None,
        initiator_id: Optional[int] = None,
        initiator_name: str = "system",
    ) -> SpecialAudit:
        audit_no = generate_audit_no()
        audit = SpecialAudit(
            audit_no=audit_no,
            title=title,
            audit_type=audit_type,
            target_user_ids=target_user_ids,
            target_system_codes=target_system_codes,
            initiator_id=initiator_id,
            status="running",
            started_at=datetime.now(),
            created_at=datetime.now(),
        )
        db.add(audit)
        db.commit()
        db.refresh(audit)

        log_audit(
            db=db,
            action="create_special_audit",
            action_type="audit",
            target_type="special_audit",
            target_id=audit.id,
            details=(
                f"创建专项审计[{audit_no}]，"
                f"目标用户数: {len(target_user_ids) if target_user_ids else '全部'}，"
                f"目标系统数: {len(target_system_codes) if target_system_codes else '全部'}"
            ),
            username=initiator_name,
            status="success",
        )

        logger.info(f"创建专项审计[{audit_no}]: {title}")
        return audit

    @classmethod
    def run_audit(
        cls,
        db: Session,
        audit_id: int,
    ) -> Dict:
        audit = db.query(SpecialAudit).get(audit_id)
        if not audit:
            return {"error": "审计任务不存在"}

        audit.status = "running"
        db.commit()

        result = cls._collect_audit_data(db, audit)
        summary = cls._generate_audit_summary(result)

        audit.status = "completed"
        audit.result_summary = summary
        audit.completed_at = datetime.now()
        db.commit()
        db.refresh(audit)

        log_audit(
            db=db,
            action="complete_special_audit",
            action_type="audit",
            target_type="special_audit",
            target_id=audit.id,
            details=f"专项审计[{audit.audit_no}]完成，{summary}",
            username="system",
            status="success",
        )

        logger.info(f"专项审计[{audit.audit_no}]执行完成")
        return {
            "audit_id": audit.id,
            "audit_no": audit.audit_no,
            "status": "completed",
            "summary": summary,
            "data": result,
        }

    @classmethod
    def _collect_audit_data(
        cls,
        db: Session,
        audit: SpecialAudit,
    ) -> Dict:
        target_user_ids = audit.target_user_ids
        target_system_codes = audit.target_system_codes

        deviations_query = db.query(PermissionDeviation)
        if target_user_ids:
            deviations_query = deviations_query.filter(
                PermissionDeviation.user_id.in_(target_user_ids)
            )
        if target_system_codes:
            deviations_query = deviations_query.filter(
                PermissionDeviation.system_code.in_(target_system_codes)
            )
        deviations = deviations_query.order_by(
            PermissionDeviation.created_at.desc()
        ).all()

        history_query = db.query(PermissionChangeHistory)
        if target_user_ids:
            history_query = history_query.filter(
                PermissionChangeHistory.user_id.in_(target_user_ids)
            )
        if target_system_codes:
            history_query = history_query.filter(
                PermissionChangeHistory.system_code.in_(target_system_codes)
            )
        change_histories = history_query.order_by(
            PermissionChangeHistory.created_at.desc()
        ).all()

        snapshots_query = db.query(PermissionSnapshot)
        if target_user_ids:
            snapshots_query = snapshots_query.filter(
                PermissionSnapshot.user_id.in_(target_user_ids)
            )
        if target_system_codes:
            snapshots_query = snapshots_query.filter(
                PermissionSnapshot.system_code.in_(target_system_codes)
            )
        snapshots = snapshots_query.order_by(
            PermissionSnapshot.created_at.desc()
        ).all()

        deviations_detail = []
        for dev in deviations:
            user = db.query(User).get(dev.user_id)
            deviations_detail.append({
                "id": dev.id,
                "username": user.username if user else "-",
                "full_name": user.full_name if user else "-",
                "system_code": dev.system_code,
                "system_name": get_system_name(dev.system_code),
                "permission_name": dev.permission_name,
                "deviation_type": dev.deviation_type,
                "deviation_type_text": get_deviation_type_text(dev.deviation_type),
                "risk_level": dev.risk_level,
                "risk_level_text": get_risk_level_text(dev.risk_level),
                "risk_score": dev.risk_score,
                "status": dev.status,
                "description": dev.description,
                "created_at": dev.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            })

        history_detail = []
        for hist in change_histories:
            user = db.query(User).get(hist.user_id)
            history_detail.append({
                "id": hist.id,
                "username": user.username if user else "-",
                "full_name": user.full_name if user else "-",
                "system_code": hist.system_code,
                "system_name": get_system_name(hist.system_code),
                "permission_code": hist.permission_code,
                "change_type": hist.change_type,
                "change_type_text": "授予" if hist.change_type == "grant" else "撤销",
                "old_value": hist.old_value,
                "new_value": hist.new_value,
                "operator": hist.operator,
                "change_reason": hist.change_reason,
                "source": hist.source,
                "created_at": hist.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            })

        return {
            "total_deviations": len(deviations),
            "deviations_by_risk": cls._count_by_field(deviations, "risk_level"),
            "deviations_by_system": cls._count_by_field(deviations, "system_code"),
            "deviations_by_status": cls._count_by_field(deviations, "status"),
            "total_changes": len(change_histories),
            "changes_by_type": cls._count_by_field(change_histories, "change_type"),
            "changes_by_system": cls._count_by_field(change_histories, "system_code"),
            "total_snapshots": len(snapshots),
            "deviations_detail": deviations_detail,
            "change_history_detail": history_detail,
        }

    @classmethod
    def _count_by_field(cls, items: List, field_name: str) -> Dict[str, int]:
        counts = {}
        for item in items:
            value = getattr(item, field_name, None)
            if value is not None:
                counts[value] = counts.get(value, 0) + 1
        return counts

    @classmethod
    def _generate_audit_summary(cls, result: Dict) -> str:
        parts = []
        parts.append(f"共发现权限偏离 {result['total_deviations']} 项")

        risk = result.get("deviations_by_risk", {})
        if risk:
            high = risk.get("high", 0)
            medium = risk.get("medium", 0)
            low = risk.get("low", 0)
            parts.append(f"（高危{high}项、中危{medium}项、低危{low}项）")

        parts.append(f"，权限变更记录 {result['total_changes']} 条")
        parts.append(f"，涉及权限快照 {result['total_snapshots']} 个。")

        return "".join(parts)

    @classmethod
    def get_audits(
        cls,
        db: Session,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[SpecialAudit], int]:
        query = db.query(SpecialAudit)
        if status:
            query = query.filter(SpecialAudit.status == status)

        total = query.count()
        audits = (
            query.order_by(SpecialAudit.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return audits, total


class ChangeHistoryService:
    @classmethod
    def get_user_change_history(
        cls,
        db: Session,
        user_id: int,
        system_code: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[PermissionChangeHistory], int]:
        query = db.query(PermissionChangeHistory).filter(
            PermissionChangeHistory.user_id == user_id
        )
        if system_code:
            query = query.filter(PermissionChangeHistory.system_code == system_code)
        if start_date:
            query = query.filter(PermissionChangeHistory.created_at >= start_date)
        if end_date:
            query = query.filter(PermissionChangeHistory.created_at <= end_date)

        total = query.count()
        histories = (
            query.order_by(PermissionChangeHistory.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return histories, total

    @classmethod
    def get_system_change_history(
        cls,
        db: Session,
        system_code: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[PermissionChangeHistory], int]:
        query = db.query(PermissionChangeHistory).filter(
            PermissionChangeHistory.system_code == system_code
        )
        if start_date:
            query = query.filter(PermissionChangeHistory.created_at >= start_date)
        if end_date:
            query = query.filter(PermissionChangeHistory.created_at <= end_date)

        total = query.count()
        histories = (
            query.order_by(PermissionChangeHistory.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return histories, total

    @classmethod
    def summarize_changes(
        cls,
        db: Session,
        user_ids: Optional[List[int]] = None,
        system_codes: Optional[List[str]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict:
        query = db.query(PermissionChangeHistory)
        if user_ids:
            query = query.filter(PermissionChangeHistory.user_id.in_(user_ids))
        if system_codes:
            query = query.filter(PermissionChangeHistory.system_code.in_(system_codes))
        if start_date:
            query = query.filter(PermissionChangeHistory.created_at >= start_date)
        if end_date:
            query = query.filter(PermissionChangeHistory.created_at <= end_date)

        histories = query.all()

        by_user: Dict[int, int] = {}
        by_system: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        by_operator: Dict[str, int] = {}

        for h in histories:
            by_user[h.user_id] = by_user.get(h.user_id, 0) + 1
            by_system[h.system_code] = by_system.get(h.system_code, 0) + 1
            by_type[h.change_type] = by_type.get(h.change_type, 0) + 1
            if h.operator:
                by_operator[h.operator] = by_operator.get(h.operator, 0) + 1

        return {
            "total_changes": len(histories),
            "by_user": by_user,
            "by_system": by_system,
            "by_type": by_type,
            "by_operator": by_operator,
        }
