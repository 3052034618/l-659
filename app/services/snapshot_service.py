from datetime import date, datetime
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models import PermissionSnapshot, User, PermissionChangeHistory
from app.core.config import settings
from app.utils import logger, log_audit
import random


class SnapshotSyncService:
    MOCK_PERMISSIONS = {
        "ERP": [
            {"code": "erp:view:finance", "name": "查看财务报表", "type": "read"},
            {"code": "erp:edit:order", "name": "编辑订单", "type": "write"},
            {"code": "erp:approve:payment", "name": "审批付款", "type": "approve"},
            {"code": "erp:view:inventory", "name": "查看库存", "type": "read"},
            {"code": "erp:manage:supplier", "name": "管理供应商", "type": "write"},
            {"code": "erp:delete:order", "name": "删除订单", "type": "delete"},
            {"code": "erp:export:report", "name": "导出报表", "type": "read"},
            {"code": "erp:manage:user", "name": "用户管理", "type": "admin"},
        ],
        "OA": [
            {"code": "oa:view:notice", "name": "查看公告", "type": "read"},
            {"code": "oa:edit:notice", "name": "编辑公告", "type": "write"},
            {"code": "oa:approve:leave", "name": "审批请假", "type": "approve"},
            {"code": "oa:view:attendance", "name": "查看考勤", "type": "read"},
            {"code": "oa:manage:department", "name": "部门管理", "type": "admin"},
            {"code": "oa:initiate:process", "name": "发起流程", "type": "write"},
        ],
        "CRM": [
            {"code": "crm:view:customer", "name": "查看客户", "type": "read"},
            {"code": "crm:edit:customer", "name": "编辑客户", "type": "write"},
            {"code": "crm:view:contract", "name": "查看合同", "type": "read"},
            {"code": "crm:approve:discount", "name": "审批折扣", "type": "approve"},
            {"code": "crm:delete:customer", "name": "删除客户", "type": "delete"},
            {"code": "crm:export:customer", "name": "导出客户", "type": "read"},
        ],
        "FINANCE": [
            {"code": "finance:view:voucher", "name": "查看凭证", "type": "read"},
            {"code": "finance:edit:voucher", "name": "编辑凭证", "type": "write"},
            {"code": "finance:approve:voucher", "name": "审核凭证", "type": "approve"},
            {"code": "finance:view:budget", "name": "查看预算", "type": "read"},
            {"code": "finance:manage:account", "name": "科目管理", "type": "admin"},
            {"code": "finance:close:period", "name": "期末结账", "type": "admin"},
        ],
    }

    @classmethod
    def _generate_mock_permissions(cls, system_code: str, user_role: str = "user") -> Dict[str, bool]:
        permissions = {}
        perms_list = cls.MOCK_PERMISSIONS.get(system_code, [])

        for perm in perms_list:
            perm_type = perm["type"]
            if user_role == "admin":
                permissions[perm["code"]] = True
            elif user_role == "manager":
                if perm_type in ["read", "write", "approve"]:
                    permissions[perm["code"]] = random.random() > 0.2
                else:
                    permissions[perm["code"]] = random.random() > 0.7
            else:
                if perm_type == "read":
                    permissions[perm["code"]] = random.random() > 0.1
                elif perm_type == "write":
                    permissions[perm["code"]] = random.random() > 0.4
                elif perm_type == "approve":
                    permissions[perm["code"]] = random.random() > 0.7
                else:
                    permissions[perm["code"]] = random.random() > 0.9

        return permissions

    @classmethod
    def _fetch_business_system_permissions(
        cls,
        system_code: str,
        user: User,
        db: Session,
    ) -> Optional[Dict[str, bool]]:
        try:
            system_info = next(
                (s for s in settings.BUSINESS_SYSTEMS if s["code"] == system_code),
                None
            )
            if not system_info:
                logger.warning(f"未找到系统配置: {system_code}")
                return None

            permissions = cls._generate_mock_permissions(system_code, user.role)
            logger.info(f"从{system_info['name']}获取用户[{user.username}]权限: {len(permissions)}项")
            return permissions

        except Exception as e:
            logger.error(f"获取业务系统[{system_code}]权限失败: {str(e)}")
            return None

    @classmethod
    def sync_user_system_snapshot(
        cls,
        db: Session,
        user: User,
        system_code: str,
        snapshot_date: Optional[date] = None,
        trigger_by: str = "system",
    ) -> Optional[PermissionSnapshot]:
        snapshot_date = snapshot_date or date.today()

        existing = db.query(PermissionSnapshot).filter(
            and_(
                PermissionSnapshot.user_id == user.id,
                PermissionSnapshot.system_code == system_code,
                PermissionSnapshot.snapshot_date == snapshot_date,
            )
        ).first()

        if existing:
            logger.info(f"用户[{user.username}]在{system_code}的快照已存在，跳过")
            return existing

        permissions = cls._fetch_business_system_permissions(system_code, user, db)
        if permissions is None:
            return None

        last_snapshot = db.query(PermissionSnapshot).filter(
            and_(
                PermissionSnapshot.user_id == user.id,
                PermissionSnapshot.system_code == system_code,
            )
        ).order_by(PermissionSnapshot.snapshot_date.desc()).first()

        if last_snapshot and last_snapshot.permissions:
            cls._record_changes(
                db=db,
                user=user,
                system_code=system_code,
                old_perms=last_snapshot.permissions,
                new_perms=permissions,
                trigger_by=trigger_by,
            )

        snapshot = PermissionSnapshot(
            user_id=user.id,
            system_code=system_code,
            snapshot_date=snapshot_date,
            permissions=permissions,
            sync_source=trigger_by,
            is_processed=False,
            created_at=datetime.now(),
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        log_audit(
            db=db,
            action="sync_permission_snapshot",
            action_type="sync",
            target_type="user",
            target_id=user.id,
            details=f"同步用户[{user.username}]在[{system_code}]的权限快照，共{len(permissions)}项权限",
            username=trigger_by,
            status="success",
        )

        logger.info(f"已创建用户[{user.username}]在[{system_code}]的权限快照#{snapshot.id}")
        return snapshot

    @classmethod
    def _record_changes(
        cls,
        db: Session,
        user: User,
        system_code: str,
        old_perms: Dict[str, bool],
        new_perms: Dict[str, bool],
        trigger_by: str,
    ):
        all_codes = set(old_perms.keys()) | set(new_perms.keys())
        change_count = 0

        for perm_code in all_codes:
            old_val = old_perms.get(perm_code, False)
            new_val = new_perms.get(perm_code, False)

            if old_val != new_val:
                if new_val and not old_val:
                    change_type = "grant"
                else:
                    change_type = "revoke"

                perm_info = None
                for sys_code, perms in cls.MOCK_PERMISSIONS.items():
                    if sys_code == system_code:
                        for p in perms:
                            if p["code"] == perm_code:
                                perm_info = p
                                break
                        break

                perm_name = perm_info["name"] if perm_info else perm_code

                history = PermissionChangeHistory(
                    user_id=user.id,
                    system_code=system_code,
                    permission_code=perm_code,
                    change_type=change_type,
                    old_value=old_val,
                    new_value=new_val,
                    operator=trigger_by,
                    change_reason="定期同步检测到的权限变更",
                    source="auto_sync",
                    created_at=datetime.now(),
                )
                db.add(history)
                change_count += 1

        if change_count > 0:
            logger.info(f"记录用户[{user.username}]在[{system_code}]的权限变更: {change_count}项")

    @classmethod
    def sync_all_systems_for_user(
        cls,
        db: Session,
        user: User,
        snapshot_date: Optional[date] = None,
        trigger_by: str = "system",
    ) -> List[PermissionSnapshot]:
        snapshots = []
        for sys_info in settings.BUSINESS_SYSTEMS:
            snapshot = cls.sync_user_system_snapshot(
                db=db,
                user=user,
                system_code=sys_info["code"],
                snapshot_date=snapshot_date,
                trigger_by=trigger_by,
            )
            if snapshot:
                snapshots.append(snapshot)
        return snapshots

    @classmethod
    def sync_all_users(
        cls,
        db: Session,
        system_code: Optional[str] = None,
        user_ids: Optional[List[int]] = None,
        trigger_by: str = "scheduled_task",
    ) -> Dict[str, int]:
        query = db.query(User).filter(User.is_active == True)
        if user_ids:
            query = query.filter(User.id.in_(user_ids))

        users = query.all()
        success_count = 0
        total_snapshots = 0

        for user in users:
            try:
                if system_code:
                    snapshot = cls.sync_user_system_snapshot(db, user, system_code, trigger_by=trigger_by)
                    if snapshot:
                        success_count += 1
                        total_snapshots += 1
                else:
                    snapshots = cls.sync_all_systems_for_user(db, user, trigger_by=trigger_by)
                    if snapshots:
                        success_count += 1
                        total_snapshots += len(snapshots)
            except Exception as e:
                logger.error(f"同步用户[{user.username}]失败: {str(e)}")
                continue

        result = {
            "total_users": len(users),
            "success_users": success_count,
            "total_snapshots": total_snapshots,
        }
        logger.info(f"权限快照同步完成: {result}")
        return result

    @classmethod
    def get_unprocessed_snapshots(cls, db: Session) -> List[PermissionSnapshot]:
        return db.query(PermissionSnapshot).filter(
            PermissionSnapshot.is_processed == False
        ).all()

    @classmethod
    def mark_snapshot_processed(cls, db: Session, snapshot_id: int) -> bool:
        snapshot = db.query(PermissionSnapshot).get(snapshot_id)
        if snapshot:
            snapshot.is_processed = True
            db.commit()
            return True
        return False
