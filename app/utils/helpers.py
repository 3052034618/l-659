import uuid
import hashlib
from datetime import datetime, date, timedelta
from typing import Optional, Tuple, List
from sqlalchemy.orm import Session
from app.models import AuditLog
from app.utils.logger import logger


def generate_ticket_no(prefix: str = "TK") -> str:
    now = datetime.now()
    date_part = now.strftime("%Y%m%d")
    random_part = str(uuid.uuid4().hex)[:6].upper()
    seq_part = str(int(now.timestamp() * 1000))[-4:]
    return f"{prefix}{date_part}{seq_part}{random_part}"


def generate_audit_no(prefix: str = "SA") -> str:
    now = datetime.now()
    date_part = now.strftime("%Y%m%d")
    random_part = str(uuid.uuid4().hex)[:6].upper()
    return f"{prefix}{date_part}{random_part}"


def calculate_date_range(days: int = 7) -> Tuple[date, date]:
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)
    return start_date, end_date


def calculate_risk_score(
    deviation_type: str,
    system_importance: int,
    is_required: bool = True
) -> Tuple[float, str]:
    base_scores = {
        "excessive": 60,
        "deficient": 30,
    }
    base = base_scores.get(deviation_type, 30)
    importance_weight = min(system_importance, 5) / 5.0
    required_multiplier = 1.5 if is_required else 1.0
    type_multiplier = 1.2 if deviation_type == "excessive" else 1.0

    risk_score = base * importance_weight * required_multiplier * type_multiplier
    risk_score = min(100, risk_score)

    from app.core.config import settings
    if risk_score >= settings.HIGH_RISK_THRESHOLD:
        risk_level = "high"
    elif risk_score >= settings.MEDIUM_RISK_THRESHOLD:
        risk_level = "medium"
    else:
        risk_level = "low"

    return round(risk_score, 1), risk_level


def get_deviation_type_text(deviation_type: str) -> str:
    mapping = {
        "excessive": "权限过高（实际拥有但不应拥有）",
        "deficient": "权限过低（应拥有但实际未拥有）",
    }
    return mapping.get(deviation_type, deviation_type)


def get_risk_level_text(risk_level: str) -> str:
    mapping = {
        "high": "高危",
        "medium": "中危",
        "low": "低危",
    }
    return mapping.get(risk_level, risk_level)


def get_status_text(status: str) -> str:
    mapping = {
        "pending": "待处理",
        "processing": "处理中",
        "resolved": "已解决",
        "closed": "已关闭",
        "running": "进行中",
        "completed": "已完成",
    }
    return mapping.get(status, status)


def log_audit(
    db: Session,
    action: str,
    action_type: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    details: Optional[str] = None,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    ip_address: Optional[str] = None,
    status: str = "success",
) -> AuditLog:
    try:
        log_entry = AuditLog(
            user_id=user_id,
            username=username,
            action=action,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            details=details,
            ip_address=ip_address,
            status=status,
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
        logger.info(f"审计日志: {action} - {username or 'system'} - {details or ''}")
        return log_entry
    except Exception as e:
        logger.error(f"记录审计日志失败: {str(e)}")
        db.rollback()
        raise


def get_system_importance(system_code: str) -> int:
    from app.core.config import settings
    for sys_info in settings.BUSINESS_SYSTEMS:
        if sys_info["code"] == system_code:
            return sys_info.get("importance", 3)
    return 3


def get_system_name(system_code: str) -> str:
    from app.core.config import settings
    for sys_info in settings.BUSINESS_SYSTEMS:
        if sys_info["code"] == system_code:
            return sys_info.get("name", system_code)
    return system_code
