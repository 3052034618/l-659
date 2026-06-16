from datetime import datetime, timedelta
from typing import List, Optional, Dict, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models import AuditTicket, PermissionDeviation, User
from app.core.config import settings
from app.utils import (
    logger,
    log_audit,
    generate_ticket_no,
    get_risk_level_text,
    notification,
)


class TicketService:
    @classmethod
    def auto_generate_tickets(
        cls,
        db: Session,
    ) -> List[AuditTicket]:
        high_risk_deviations = db.query(PermissionDeviation).filter(
            and_(
                PermissionDeviation.risk_level == "high",
                PermissionDeviation.status == "pending",
            )
        ).all()

        tickets = []
        for deviation in high_risk_deviations:
            existing_ticket = db.query(AuditTicket).filter(
                AuditTicket.deviation_id == deviation.id
            ).first()
            if existing_ticket:
                continue

            ticket = cls.create_ticket_for_deviation(db, deviation)
            if ticket:
                tickets.append(ticket)

        logger.info(f"自动生成审计工单: {len(tickets)}个")
        return tickets

    @classmethod
    def create_ticket_for_deviation(
        cls,
        db: Session,
        deviation: PermissionDeviation,
    ) -> Optional[AuditTicket]:
        try:
            user = db.query(User).get(deviation.user_id)
            ticket_no = generate_ticket_no()

            priority_map = {"high": "urgent", "medium": "high", "low": "normal"}
            priority = priority_map.get(deviation.risk_level, "normal")

            title = (
                f"[{get_risk_level_text(deviation.risk_level)}]权限偏离-"
                f"{deviation.system_code}-{user.full_name if user else '未知用户'}-"
                f"{deviation.permission_name}"
            )

            assignee = cls._find_security_admin(db)

            ticket = AuditTicket(
                ticket_no=ticket_no,
                deviation_id=deviation.id,
                title=title,
                status="pending",
                assignee_id=assignee.id if assignee else None,
                priority=priority,
                escalated=False,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add(ticket)
            db.commit()
            db.refresh(ticket)

            deviation.status = "processing"
            db.commit()

            log_audit(
                db=db,
                action="create_audit_ticket",
                action_type="ticket",
                target_type="ticket",
                target_id=ticket.id,
                details=(
                    f"自动创建工单[{ticket_no}]，"
                    f"偏离ID#{deviation.id}，"
                    f"分配给: {assignee.username if assignee else '未分配'}"
                ),
                username="system",
                status="success",
            )

            logger.info(f"创建审计工单[{ticket_no}]，分配给: {assignee.username if assignee else '未分配'}")
            return ticket

        except Exception as e:
            logger.error(f"创建工单失败: {str(e)}")
            db.rollback()
            return None

    @classmethod
    def _find_security_admin(cls, db: Session) -> Optional[User]:
        admin = db.query(User).filter(
            and_(User.role == "security_admin", User.is_active == True)
        ).first()
        if admin:
            return admin

        admin = db.query(User).filter(
            and_(User.role == "admin", User.is_active == True)
        ).first()
        return admin

    @classmethod
    def _find_security_director(cls, db: Session) -> Optional[User]:
        director = db.query(User).filter(
            and_(User.role == "security_director", User.is_active == True)
        ).first()
        if director:
            return director

        director = db.query(User).filter(
            and_(User.role == "admin", User.is_active == True)
        ).first()
        return director

    @classmethod
    def check_and_upgrade_tickets(
        cls,
        db: Session,
    ) -> List[AuditTicket]:
        upgrade_threshold = datetime.now() - timedelta(hours=settings.UPGRADE_HOURS)

        pending_tickets = db.query(AuditTicket).filter(
            and_(
                AuditTicket.status.in_(["pending", "processing"]),
                AuditTicket.escalated == False,
                AuditTicket.created_at < upgrade_threshold,
            )
        ).all()

        upgraded_tickets = []
        for ticket in pending_tickets:
            upgraded = cls._upgrade_ticket(db, ticket)
            if upgraded:
                upgraded_tickets.append(upgraded)

        if upgraded_tickets:
            logger.info(f"工单升级完成: {len(upgraded_tickets)}个工单已升级")
        return upgraded_tickets

    @classmethod
    def _upgrade_ticket(
        cls,
        db: Session,
        ticket: AuditTicket,
    ) -> Optional[AuditTicket]:
        try:
            director = cls._find_security_director(db)

            ticket.escalated = True
            ticket.escalated_at = datetime.now()
            ticket.escalated_to = director.id if director else None
            ticket.priority = "critical"
            ticket.updated_at = datetime.now()
            db.commit()
            db.refresh(ticket)

            assignee = db.query(User).get(ticket.assignee_id) if ticket.assignee_id else None
            ticket_data = {
                "ticket_no": ticket.ticket_no,
                "title": ticket.title,
                "assignee_name": assignee.full_name if assignee else "未分配",
                "created_at": ticket.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }
            notification.send_ticket_escalation_alert(ticket_data)

            log_audit(
                db=db,
                action="upgrade_ticket",
                action_type="escalation",
                target_type="ticket",
                target_id=ticket.id,
                details=(
                    f"工单[{ticket.ticket_no}]超时未处理，"
                    f"已升级至安全总监处理，"
                    f"原处理人: {assignee.username if assignee else '未分配'}"
                ),
                username="system",
                status="success",
            )

            logger.warning(f"工单[{ticket.ticket_no}]已升级至安全总监")
            return ticket

        except Exception as e:
            logger.error(f"工单升级失败[{ticket.ticket_no}]: {str(e)}")
            db.rollback()
            return None

    @classmethod
    def assign_ticket(
        cls,
        db: Session,
        ticket_id: int,
        assignee_id: int,
        operator_name: str,
    ) -> Optional[AuditTicket]:
        ticket = db.query(AuditTicket).get(ticket_id)
        if not ticket:
            return None

        assignee = db.query(User).get(assignee_id)
        if not assignee:
            return None

        ticket.assignee_id = assignee_id
        ticket.status = "processing"
        ticket.updated_at = datetime.now()
        db.commit()
        db.refresh(ticket)

        log_audit(
            db=db,
            action="assign_ticket",
            action_type="assignment",
            target_type="ticket",
            target_id=ticket.id,
            details=f"工单[{ticket.ticket_no}]分配给: {assignee.username}",
            username=operator_name,
            status="success",
        )

        return ticket

    @classmethod
    def resolve_ticket(
        cls,
        db: Session,
        ticket_id: int,
        resolution: str,
        action_type: str,
        resolver_id: int,
        resolver_name: str,
        remarks: Optional[str] = None,
    ) -> Tuple[bool, Optional[AuditTicket], str]:
        ticket = db.query(AuditTicket).get(ticket_id)
        if not ticket:
            return False, None, "工单不存在"

        from app.services.deviation_service import DeviationDetectionService

        deviation = db.query(PermissionDeviation).get(ticket.deviation_id)
        if deviation:
            success, dev, message = DeviationDetectionService.resolve_deviation(
                db=db,
                deviation_id=deviation.id,
                action_type=action_type,
                operator_name=resolver_name,
                remarks=remarks,
            )
            if not success:
                log_audit(
                    db=db,
                    action="resolve_ticket_failed",
                    action_type="resolution",
                    target_type="ticket",
                    target_id=ticket.id,
                    details=f"工单[{ticket.ticket_no}]处理失败: {message}",
                    username=resolver_name,
                    status="failed",
                )
                logger.warning(f"工单[{ticket.ticket_no}]处理失败: {message}，工单保持打开状态")
                return False, ticket, message

        ticket.status = "resolved"
        ticket.resolution = resolution
        ticket.action_type = action_type
        ticket.remarks = remarks
        ticket.resolved_at = datetime.now()
        ticket.resolved_by = resolver_id
        ticket.updated_at = datetime.now()
        db.commit()
        db.refresh(ticket)

        log_audit(
            db=db,
            action="resolve_ticket",
            action_type="resolution",
            target_type="ticket",
            target_id=ticket.id,
            details=(
                f"工单[{ticket.ticket_no}]已解决，"
                f"处理方式: {action_type}，"
                f"处理结果: {resolution[:100]}"
            ),
            username=resolver_name,
            status="success",
        )

        logger.info(f"工单[{ticket.ticket_no}]已由{resolver_name}解决")
        return True, ticket, "处理成功"

    @classmethod
    def get_tickets(
        cls,
        db: Session,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        assignee_id: Optional[int] = None,
        escalated: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[AuditTicket], int]:
        query = db.query(AuditTicket)

        if status:
            query = query.filter(AuditTicket.status == status)
        if priority:
            query = query.filter(AuditTicket.priority == priority)
        if assignee_id:
            query = query.filter(AuditTicket.assignee_id == assignee_id)
        if escalated is not None:
            query = query.filter(AuditTicket.escalated == escalated)

        total = query.count()
        tickets = (
            query.order_by(AuditTicket.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return tickets, total

    @classmethod
    def get_ticket_statistics(cls, db: Session) -> Dict:
        all_tickets = db.query(AuditTicket).all()
        by_status = {}
        by_priority = {}
        escalated_count = 0

        for ticket in all_tickets:
            by_status[ticket.status] = by_status.get(ticket.status, 0) + 1
            by_priority[ticket.priority] = by_priority.get(ticket.priority, 0) + 1
            if ticket.escalated:
                escalated_count += 1

        return {
            "total": len(all_tickets),
            "by_status": by_status,
            "by_priority": by_priority,
            "escalated_count": escalated_count,
        }
