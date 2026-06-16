from datetime import date, datetime
from typing import Optional, List, Dict, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models import PermissionSnapshot, User, PermissionChangeHistory
from app.core.config import settings
from app.utils import logger, log_audit
from app.services.business_system_adapter import get_business_system_adapter, AdapterFactory
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
    ) -> Tuple[Optional[Dict[str, bool]], str]:
        try:
            system_info = next(
                (s for s in settings.BUSINESS_SYSTEMS if s["code"] == system_code),
                None
            )
            if not system_info:
                return None, f"未找到系统配置: {system_code}"

            adapter = get_business_system_adapter()
            success, permissions, message = adapter.fetch_permissions(user.username, system_code)

            if not success or permissions is None:
                logger.error(f"获取{system_info['name']}用户[{user.username}]权限失败: {message}")
                return None, message

            logger.info(f"从{system_info['name']}获取用户[{user.username}]权限: {len(permissions)}项 - {message}")
            return permissions, message

        except Exception as e:
            error_msg = f"获取业务系统[{system_code}]权限异常: {str(e)}"
            logger.error(error_msg)
            return None, error_msg

    @classmethod
    def sync_user_system_snapshot(
        cls,
        db: Session,
        user: User,
        system_code: str,
        snapshot_date: Optional[date] = None,
        trigger_by: str = "system",
    ) -> Tuple[Optional[PermissionSnapshot], str]:
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
            return existing, "快照已存在，跳过同步"

        permissions, message = cls._fetch_business_system_permissions(system_code, user, db)
        if permissions is None:
            log_audit(
                db=db,
                action="sync_snapshot_failed",
                action_type="sync",
                target_type="user",
                target_id=user.id,
                details=f"同步用户[{user.username}]在[{system_code}]的权限快照失败: {message}",
                username=trigger_by,
                status="failed",
            )
            logger.warning(f"用户[{user.username}]在{system_code}的快照同步失败: {message}")
            return None, message

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
        return snapshot, "同步成功"

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
            snapshot, _ = cls.sync_user_system_snapshot(
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
    ) -> Dict:
        query = db.query(User).filter(User.is_active == True)
        if user_ids:
            query = query.filter(User.id.in_(user_ids))

        users = query.all()
        success_count = 0
        total_snapshots = 0
        failed_items = []

        for user in users:
            user_failures = []
            user_success_count = 0
            if system_code:
                snapshot, message = cls.sync_user_system_snapshot(db, user, system_code, trigger_by=trigger_by)
                if snapshot:
                    success_count += 1
                    total_snapshots += 1
                    user_success_count = 1
                else:
                    sys_info = next((s for s in settings.BUSINESS_SYSTEMS if s["code"] == system_code), None)
                    user_failures.append({
                        "system_code": system_code,
                        "system_name": sys_info["name"] if sys_info else system_code,
                        "reason": message,
                    })
            else:
                for sys_info in settings.BUSINESS_SYSTEMS:
                    snapshot, message = cls.sync_user_system_snapshot(
                        db=db,
                        user=user,
                        system_code=sys_info["code"],
                        trigger_by=trigger_by,
                    )
                    if snapshot:
                        total_snapshots += 1
                        user_success_count += 1
                    else:
                        user_failures.append({
                            "system_code": sys_info["code"],
                            "system_name": sys_info["name"],
                            "reason": message,
                        })
                if user_success_count > 0:
                    success_count += 1

            if user_failures:
                failed_items.append({
                    "user_id": user.id,
                    "username": user.username,
                    "full_name": user.full_name,
                    "failed_systems": user_failures,
                })

        all_success = len(failed_items) == 0 and total_snapshots > 0

        result = {
            "total_users": len(users),
            "success_users": success_count,
            "failed_users": len(failed_items),
            "total_snapshots": total_snapshots,
            "failed_items": failed_items,
            "all_success": all_success,
        }
        logger.info(f"权限快照同步完成: 成功{total_snapshots}个快照，失败{len(failed_items)}个用户")
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

    @classmethod
    def adjust_user_permission(
        cls,
        db: Session,
        user: User,
        system_code: str,
        permission_code: str,
        grant: bool,
        operator_name: str = "system",
    ) -> Tuple[bool, str]:
        """
        调整用户权限：调用业务系统接口调整权限，更新本地快照，记录变更历史
        返回: (success: bool, message: str)
        """
        from app.services.business_system_adapter import get_business_system_adapter
        from app.utils import get_system_name

        adapter = get_business_system_adapter()

        action_text = "授予" if grant else "撤销"
        sys_name = get_system_name(system_code)

        logger.info(
            f"[{operator_name}]正在{action_text}用户[{user.username}]在[{sys_name}]的权限[{permission_code}]"
        )

        success, message = adapter.adjust_permission(
            user.username, system_code, permission_code, grant
        )

        if not success:
            logger.error(f"调整权限失败: {message}")
            return False, message

        current_snapshot = db.query(PermissionSnapshot).filter(
            and_(
                PermissionSnapshot.user_id == user.id,
                PermissionSnapshot.system_code == system_code,
            )
        ).order_by(PermissionSnapshot.snapshot_date.desc()).first()

        old_perms = current_snapshot.permissions.copy() if current_snapshot and current_snapshot.permissions else {}
        new_perms = old_perms.copy()
        new_perms[permission_code] = grant

        change_type = "grant" if grant else "revoke"
        old_val = old_perms.get(permission_code, False)
        new_val = grant

        if old_val == new_val:
            logger.info(f"权限[{permission_code}]已是{new_val}，无需变更")
            return True, f"权限已是{action_text}状态，无需变更"

        perm_info = None
        for sys_c, perms in cls.MOCK_PERMISSIONS.items():
            if sys_c == system_code:
                for p in perms:
                    if p["code"] == permission_code:
                        perm_info = p
                        break
                break

        perm_name = perm_info["name"] if perm_info else permission_code

        history = PermissionChangeHistory(
            user_id=user.id,
            system_code=system_code,
            permission_code=permission_code,
            change_type=change_type,
            old_value=old_val,
            new_value=new_val,
            operator=operator_name,
            change_reason=f"审计工单处理，{action_text}权限[{perm_name}]",
            source="audit_ticket",
            created_at=datetime.now(),
        )
        db.add(history)

        new_snapshot = PermissionSnapshot(
            user_id=user.id,
            system_code=system_code,
            snapshot_date=date.today(),
            permissions=new_perms,
            sync_source="audit_adjustment",
            is_processed=False,
            created_at=datetime.now(),
        )
        db.add(new_snapshot)
        db.commit()

        log_audit(
            db=db,
            action="adjust_user_permission",
            action_type="adjust",
            target_type="user",
            target_id=user.id,
            details=f"{action_text}用户[{user.username}]在[{sys_name}]的权限[{perm_name}]",
            username=operator_name,
            status="success",
        )

        logger.info(f"权限调整成功：{action_text}[{permission_code}]，已生成新快照#{new_snapshot.id}和变更历史")
        return True, f"已成功{action_text}权限[{perm_name}]，变更已记录"
