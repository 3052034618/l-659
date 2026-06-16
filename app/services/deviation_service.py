from datetime import datetime
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models import (
    PermissionSnapshot,
    PermissionDeviation,
    PermissionMatrix,
    User,
    Position,
)
from app.utils import (
    logger,
    log_audit,
    calculate_risk_score,
    get_deviation_type_text,
    get_risk_level_text,
    get_system_importance,
    notification,
)


class DeviationDetectionService:
    @classmethod
    def get_position_permission_matrix(
        cls,
        db: Session,
        position_id: int,
        system_code: str,
    ) -> Dict[str, Dict]:
        matrix_entries = db.query(PermissionMatrix).filter(
            and_(
                PermissionMatrix.position_id == position_id,
                PermissionMatrix.system_code == system_code,
            )
        ).all()

        matrix = {}
        for entry in matrix_entries:
            matrix[entry.permission_code] = {
                "permission_code": entry.permission_code,
                "permission_name": entry.permission_name,
                "is_required": entry.is_required,
                "standard_value": True,
                "permission_type": entry.permission_type,
            }
        return matrix

    @classmethod
    def compare_permissions(
        cls,
        db: Session,
        snapshot: PermissionSnapshot,
        user: User,
    ) -> List[Dict]:
        deviations = []

        if not user.position_id:
            logger.warning(f"用户[{user.username}]未分配岗位，跳过偏离检测")
            return deviations

        matrix = cls.get_position_permission_matrix(
            db, user.position_id, snapshot.system_code
        )

        actual_perms = snapshot.permissions or {}
        all_perm_codes = set(matrix.keys()) | set(actual_perms.keys())

        for perm_code in all_perm_codes:
            std_info = matrix.get(perm_code)
            actual_val = actual_perms.get(perm_code, False)
            standard_val = std_info["standard_value"] if std_info else False
            is_required = std_info["is_required"] if std_info else False
            perm_name = std_info["permission_name"] if std_info else perm_code

            deviation_type = None
            if standard_val and not actual_val and is_required:
                deviation_type = "deficient"
            elif actual_val and not standard_val:
                deviation_type = "excessive"

            if deviation_type:
                system_importance = get_system_importance(snapshot.system_code)
                risk_score, risk_level = calculate_risk_score(
                    deviation_type=deviation_type,
                    system_importance=system_importance,
                    is_required=is_required,
                )

                description = cls._build_deviation_description(
                    deviation_type=deviation_type,
                    permission_name=perm_name,
                    standard_val=standard_val,
                    actual_val=actual_val,
                    system_code=snapshot.system_code,
                )

                deviations.append({
                    "user_id": user.id,
                    "snapshot_id": snapshot.id,
                    "system_code": snapshot.system_code,
                    "permission_code": perm_code,
                    "permission_name": perm_name,
                    "deviation_type": deviation_type,
                    "standard_value": standard_val,
                    "actual_value": actual_val,
                    "risk_score": risk_score,
                    "risk_level": risk_level,
                    "description": description,
                    "is_required": is_required,
                })

        return deviations

    @classmethod
    def _build_deviation_description(
        cls,
        deviation_type: str,
        permission_name: str,
        standard_val: bool,
        actual_val: bool,
        system_code: str,
    ) -> str:
        if deviation_type == "excessive":
            return (
                f"权限过高异常：在[{system_code}]系统中，用户实际拥有权限[{permission_name}]，"
                f"但根据岗位标准该权限应为[未授权]。可能存在越权风险。"
            )
        else:
            return (
                f"权限过低异常：在[{system_code}]系统中，用户未拥有必需权限[{permission_name}]，"
                f"但根据岗位标准该权限应为[已授权]。可能影响正常业务开展。"
            )

    @classmethod
    def save_deviations(
        cls,
        db: Session,
        deviations: List[Dict],
        audit_batch_id: Optional[int] = None,
    ) -> List[PermissionDeviation]:
        saved_deviations = []
        high_risk_deviations = []

        for dev_data in deviations:
            existing = db.query(PermissionDeviation).filter(
                and_(
                    PermissionDeviation.user_id == dev_data["user_id"],
                    PermissionDeviation.system_code == dev_data["system_code"],
                    PermissionDeviation.permission_code == dev_data["permission_code"],
                    PermissionDeviation.status.in_(["pending", "processing"]),
                )
            ).first()

            if existing:
                existing.risk_score = dev_data["risk_score"]
                existing.risk_level = dev_data["risk_level"]
                existing.description = dev_data["description"]
                existing.actual_value = dev_data["actual_value"]
                existing.standard_value = dev_data["standard_value"]
                existing.snapshot_id = dev_data["snapshot_id"]
                existing.updated_at = datetime.now()
                if audit_batch_id:
                    existing.audit_batch_id = audit_batch_id
                saved_deviations.append(existing)
                if existing.risk_level == "high":
                    high_risk_deviations.append(existing)
            else:
                deviation = PermissionDeviation(
                    user_id=dev_data["user_id"],
                    snapshot_id=dev_data["snapshot_id"],
                    system_code=dev_data["system_code"],
                    permission_code=dev_data["permission_code"],
                    permission_name=dev_data["permission_name"],
                    deviation_type=dev_data["deviation_type"],
                    standard_value=dev_data["standard_value"],
                    actual_value=dev_data["actual_value"],
                    risk_score=dev_data["risk_score"],
                    risk_level=dev_data["risk_level"],
                    status="pending",
                    description=dev_data["description"],
                    audit_batch_id=audit_batch_id,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                db.add(deviation)
                saved_deviations.append(deviation)
                if deviation.risk_level == "high":
                    high_risk_deviations.append(deviation)

        db.commit()

        for dev in high_risk_deviations:
            cls._alert_high_risk_deviation(db, dev)

        return saved_deviations

    @classmethod
    def _alert_high_risk_deviation(cls, db: Session, deviation: PermissionDeviation):
        try:
            user = db.query(User).get(deviation.user_id)
            deviation_data = {
                "username": user.username if user else "-",
                "full_name": user.full_name if user else "-",
                "system_code": deviation.system_code,
                "permission_name": deviation.permission_name,
                "deviation_type_text": get_deviation_type_text(deviation.deviation_type),
                "risk_score": deviation.risk_score,
                "description": deviation.description,
            }
            notification.send_high_risk_alert(deviation_data)

            log_audit(
                db=db,
                action="high_risk_alert",
                action_type="notification",
                target_type="deviation",
                target_id=deviation.id,
                details=f"推送高危偏离预警: [{deviation.system_code}] - [{deviation.permission_name}]",
                username="system",
                status="success",
            )
        except Exception as e:
            logger.error(f"推送高危偏离预警失败: {str(e)}")

    @classmethod
    def process_snapshot(
        cls,
        db: Session,
        snapshot: PermissionSnapshot,
        audit_batch_id: Optional[int] = None,
    ) -> List[PermissionDeviation]:
        from app.services.snapshot_service import SnapshotSyncService

        user = db.query(User).get(snapshot.user_id)
        if not user:
            logger.warning(f"快照#{snapshot.id}对应的用户不存在")
            return []

        deviations_data = cls.compare_permissions(db, snapshot, user)
        saved_deviations = cls.save_deviations(db, deviations_data, audit_batch_id=audit_batch_id)

        SnapshotSyncService.mark_snapshot_processed(db, snapshot.id)

        log_audit(
            db=db,
            action="detect_deviation",
            action_type="detection",
            target_type="snapshot",
            target_id=snapshot.id,
            details=(
                f"处理快照#{snapshot.id}，检测到{len(saved_deviations)}项权限偏离，"
                f"其中高危{len([d for d in saved_deviations if d.risk_level == 'high'])}项"
            ),
            username="system",
            status="success",
        )

        logger.info(
            f"快照#{snapshot.id}偏离检测完成: 共{len(saved_deviations)}项，"
            f"高危{len([d for d in saved_deviations if d.risk_level == 'high'])}项"
        )
        return saved_deviations

    @classmethod
    def process_all_unprocessed(
        cls,
        db: Session,
    ) -> Dict:
        from app.services.snapshot_service import SnapshotSyncService
        from app.services.ticket_service import TicketService

        snapshots = SnapshotSyncService.get_unprocessed_snapshots(db)
        total_deviations = 0
        high_risk_count = 0
        failed_snapshots = 0

        for snapshot in snapshots:
            try:
                deviations = cls.process_snapshot(db, snapshot, audit_batch_id=audit_batch_id)
                total_deviations += len(deviations)
                high_risk_count += len([d for d in deviations if d.risk_level == "high"])
            except Exception as e:
                logger.error(f"处理快照#{snapshot.id}失败: {str(e)}")
                failed_snapshots += 1
                continue

        new_tickets = TicketService.auto_generate_tickets(db, audit_batch_id=audit_batch_id)
        new_ticket_count = len(new_tickets)

        result = {
            "processed_snapshots": len(snapshots),
            "failed_snapshots": failed_snapshots,
            "total_deviations": total_deviations,
            "high_risk_count": high_risk_count,
            "new_ticket_count": new_ticket_count,
        }
        logger.info(f"批量偏离检测完成: {result}")
        return result

    @classmethod
    def process_snapshots_with_batch(
        cls,
        db: Session,
        snapshot_ids: List[int],
        audit_batch_id: Optional[int] = None,
    ) -> Dict:
        from app.services.snapshot_service import SnapshotSyncService
        from app.services.ticket_service import TicketService

        if not snapshot_ids:
            return {
                "processed_snapshots": 0,
                "total_deviations": 0,
                "high_risk_count": 0,
                "medium_risk_count": 0,
                "low_risk_count": 0,
                "deviations": [],
                "new_ticket_count": 0,
            }

        snapshots = db.query(PermissionSnapshot).filter(
            PermissionSnapshot.id.in_(snapshot_ids),
            PermissionSnapshot.sync_status == "success",
        ).all()

        total_deviations = 0
        high_risk_count = 0
        medium_risk_count = 0
        low_risk_count = 0
        failed_snapshots = 0
        all_deviations = []

        for snapshot in snapshots:
            try:
                deviations = cls.process_snapshot(db, snapshot, audit_batch_id=audit_batch_id)
                total_deviations += len(deviations)
                high_risk_count += len([d for d in deviations if d.risk_level == "high"])
                medium_risk_count += len([d for d in deviations if d.risk_level == "medium"])
                low_risk_count += len([d for d in deviations if d.risk_level == "low"])
                all_deviations.extend(deviations)
            except Exception as e:
                logger.error(f"处理快照#{snapshot.id}失败: {str(e)}")
                failed_snapshots += 1
                continue

        result = {
            "processed_snapshots": len(snapshots),
            "failed_snapshots": failed_snapshots,
            "total_deviations": total_deviations,
            "high_risk_count": high_risk_count,
            "medium_risk_count": medium_risk_count,
            "low_risk_count": low_risk_count,
            "deviations": all_deviations,
            "new_ticket_count": 0,
        }
        logger.info(f"批次偏离检测完成: {audit_batch_id}, {result}")
        return result

    @classmethod
    def resolve_deviation(
        cls,
        db: Session,
        deviation_id: int,
        action_type: str,
        operator_name: str,
        remarks: Optional[str] = None,
    ) -> Tuple[bool, Optional[PermissionDeviation], str]:
        from app.services.snapshot_service import SnapshotSyncService

        deviation = db.query(PermissionDeviation).get(deviation_id)
        if not deviation:
            return False, None, "偏离记录不存在"

        user = db.query(User).get(deviation.user_id)
        if not user:
            logger.error(f"偏离记录#{deviation_id}对应的用户不存在")
            return False, deviation, "偏离记录对应的用户不存在"

        if action_type == "adjust_permission":
            grant = deviation.deviation_type == "deficient"
            success, message = SnapshotSyncService.adjust_user_permission(
                db=db,
                user=user,
                system_code=deviation.system_code,
                permission_code=deviation.permission_code,
                grant=grant,
                operator_name=operator_name,
                audit_batch_id=deviation.audit_batch_id,
            )

            if not success:
                logger.error(f"调整权限失败: {message}")
                deviation.status = "processing"
                deviation.updated_at = datetime.now()
                db.commit()
                db.refresh(deviation)

                log_audit(
                    db=db,
                    action="resolve_deviation",
                    action_type="adjust_failed",
                    target_type="deviation",
                    target_id=deviation.id,
                    details=f"权限调整失败: {message}",
                    username=operator_name,
                    status="failed",
                )
                return False, deviation, message

            deviation.status = "resolved"
            deviation.resolved_action = "adjusted"
            deviation.resolved_at = datetime.now()
            deviation.updated_at = datetime.now()
            db.commit()
            db.refresh(deviation)

            log_audit(
                db=db,
                action="resolve_deviation",
                action_type="adjust_permission",
                target_type="deviation",
                target_id=deviation.id,
                details=f"已调整权限，{message}，备注: {remarks or '无'}",
                username=operator_name,
                status="success",
            )
            return True, deviation, "权限调整成功"

        elif action_type == "update_risk":
            old_risk_level = deviation.risk_level
            old_risk_score = deviation.risk_score

            if deviation.risk_level == "high":
                deviation.risk_level = "medium"
                deviation.risk_score = min(deviation.risk_score * 0.6, 60.0)
            elif deviation.risk_level == "medium":
                deviation.risk_level = "low"
                deviation.risk_score = min(deviation.risk_score * 0.5, 30.0)

            deviation.status = "resolved"
            deviation.resolved_action = "risk_updated"
            deviation.resolved_at = datetime.now()
            deviation.updated_at = datetime.now()
            db.commit()
            db.refresh(deviation)

            log_audit(
                db=db,
                action="resolve_deviation",
                action_type="update_risk",
                target_type="deviation",
                target_id=deviation.id,
                details=(
                    f"已更新风险标记: {old_risk_level}({old_risk_score}) → "
                    f"{deviation.risk_level}({deviation.risk_score})，备注: {remarks or '无'}"
                ),
                username=operator_name,
                status="success",
            )
            return True, deviation, "风险标记更新成功"

        else:
            deviation.status = "resolved"
            deviation.resolved_action = "marked"
            deviation.resolved_at = datetime.now()
            deviation.updated_at = datetime.now()
            db.commit()
            db.refresh(deviation)

            log_audit(
                db=db,
                action="resolve_deviation",
                action_type="mark_resolved",
                target_type="deviation",
                target_id=deviation.id,
                details=f"标记为已解决，备注: {remarks or '无'}",
                username=operator_name,
                status="success",
            )
            return True, deviation, "已标记为已解决"

    @classmethod
    def get_deviation_statistics(
        cls,
        db: Session,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict:
        query = db.query(PermissionDeviation)
        if start_date:
            query = query.filter(PermissionDeviation.created_at >= start_date)
        if end_date:
            query = query.filter(PermissionDeviation.created_at <= end_date)

        all_deviations = query.all()
        total = len(all_deviations)
        by_risk = {"high": 0, "medium": 0, "low": 0}
        by_status = {"pending": 0, "processing": 0, "resolved": 0}
        by_type = {"excessive": 0, "deficient": 0}
        by_system: Dict[str, int] = {}

        for dev in all_deviations:
            by_risk[dev.risk_level] = by_risk.get(dev.risk_level, 0) + 1
            by_status[dev.status] = by_status.get(dev.status, 0) + 1
            by_type[dev.deviation_type] = by_type.get(dev.deviation_type, 0) + 1
            by_system[dev.system_code] = by_system.get(dev.system_code, 0) + 1

        resolved = [d for d in all_deviations if d.status == "resolved" and d.resolved_at]
        avg_fix_hours = 0
        if resolved:
            total_hours = sum(
                (d.resolved_at - d.created_at).total_seconds() / 3600
                for d in resolved
            )
            avg_fix_hours = round(total_hours / len(resolved), 1)

        audit_completion_rate = 0
        if total > 0:
            audit_completion_rate = round(
                (by_status["resolved"] + by_status.get("closed", 0)) / total * 100, 1
            )

        return {
            "total": total,
            "by_risk": by_risk,
            "by_status": by_status,
            "by_type": by_type,
            "by_system": by_system,
            "avg_fix_hours": avg_fix_hours,
            "audit_completion_rate": audit_completion_rate,
        }
