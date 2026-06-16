from datetime import datetime
from typing import List, Optional, Tuple, Type, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models import (
    User, Position, PermissionMatrix,
    PermissionSnapshot, PermissionDeviation,
    AuditTicket, AuditLog,
)
from app.schemas import (
    UserCreate, UserUpdate,
    PositionCreate, PositionUpdate,
    PermissionMatrixCreate,
)
from app.utils import logger, log_audit


class CRUDService:
    @staticmethod
    def _paginate(query, page: int, page_size: int):
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        return items, total

    @classmethod
    def create_user(
        cls,
        db: Session,
        data: UserCreate,
        operator_name: str = "system",
    ) -> User:
        existing = db.query(User).filter(
            (User.username == data.username) | (User.email == data.email)
        ).first()
        if existing:
            raise ValueError(f"用户名或邮箱已存在: {data.username}")

        user = User(**data.model_dump())
        db.add(user)
        db.commit()
        db.refresh(user)

        log_audit(
            db=db, action="create_user", action_type="create",
            target_type="user", target_id=user.id,
            details=f"创建用户: {user.username} ({user.full_name})",
            username=operator_name, status="success",
        )
        return user

    @classmethod
    def update_user(
        cls,
        db: Session,
        user_id: int,
        data: UserUpdate,
        operator_name: str = "system",
    ) -> Optional[User]:
        user = db.query(User).get(user_id)
        if not user:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(user, key, value)
        user.updated_at = datetime.now()

        db.commit()
        db.refresh(user)

        log_audit(
            db=db, action="update_user", action_type="update",
            target_type="user", target_id=user.id,
            details=f"更新用户信息: {user.username}, 修改字段: {list(update_data.keys())}",
            username=operator_name, status="success",
        )
        return user

    @classmethod
    def get_user(cls, db: Session, user_id: int) -> Optional[User]:
        return db.query(User).get(user_id)

    @classmethod
    def get_user_by_username(cls, db: Session, username: str) -> Optional[User]:
        return db.query(User).filter(User.username == username).first()

    @classmethod
    def list_users(
        cls,
        db: Session,
        position_id: Optional[int] = None,
        department: Optional[str] = None,
        is_active: Optional[bool] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[User], int]:
        query = db.query(User)
        if position_id:
            query = query.filter(User.position_id == position_id)
        if department:
            query = query.filter(User.department.like(f"%{department}%"))
        if is_active is not None:
            query = query.filter(User.is_active == is_active)
        if keyword:
            query = query.filter(
                (User.username.like(f"%{keyword}%")) |
                (User.full_name.like(f"%{keyword}%")) |
                (User.email.like(f"%{keyword}%"))
            )
        return cls._paginate(query.order_by(User.id.desc()), page, page_size)

    @classmethod
    def create_position(
        cls,
        db: Session,
        data: PositionCreate,
        operator_name: str = "system",
    ) -> Position:
        existing = db.query(Position).filter(
            (Position.name == data.name) | (Position.code == data.code)
        ).first()
        if existing:
            raise ValueError(f"岗位名称或编码已存在: {data.name}")

        position = Position(**data.model_dump())
        db.add(position)
        db.commit()
        db.refresh(position)

        log_audit(
            db=db, action="create_position", action_type="create",
            target_type="position", target_id=position.id,
            details=f"创建岗位: {position.name} ({position.code})",
            username=operator_name, status="success",
        )
        return position

    @classmethod
    def update_position(
        cls,
        db: Session,
        position_id: int,
        data: PositionUpdate,
        operator_name: str = "system",
    ) -> Optional[Position]:
        position = db.query(Position).get(position_id)
        if not position:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(position, key, value)
        position.updated_at = datetime.now()

        db.commit()
        db.refresh(position)
        return position

    @classmethod
    def get_position(cls, db: Session, position_id: int) -> Optional[Position]:
        return db.query(Position).get(position_id)

    @classmethod
    def list_positions(
        cls,
        db: Session,
        department: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Position], int]:
        query = db.query(Position)
        if department:
            query = query.filter(Position.department.like(f"%{department}%"))
        if keyword:
            query = query.filter(
                (Position.name.like(f"%{keyword}%")) |
                (Position.code.like(f"%{keyword}%"))
            )
        return cls._paginate(query.order_by(Position.id.desc()), page, page_size)

    @classmethod
    def create_permission_matrix(
        cls,
        db: Session,
        data: PermissionMatrixCreate,
        operator_name: str = "system",
    ) -> PermissionMatrix:
        existing = db.query(PermissionMatrix).filter(
            and_(
                PermissionMatrix.position_id == data.position_id,
                PermissionMatrix.system_code == data.system_code,
                PermissionMatrix.permission_code == data.permission_code,
            )
        ).first()
        if existing:
            raise ValueError("该岗位在此系统的该权限已存在")

        matrix = PermissionMatrix(**data.model_dump())
        db.add(matrix)
        db.commit()
        db.refresh(matrix)

        log_audit(
            db=db, action="create_permission_matrix", action_type="create",
            target_type="permission_matrix", target_id=matrix.id,
            details=f"创建权限矩阵: 岗位#{matrix.position_id}, 系统[{matrix.system_code}], 权限[{matrix.permission_name}]",
            username=operator_name, status="success",
        )
        return matrix

    @classmethod
    def list_permission_matrix(
        cls,
        db: Session,
        position_id: Optional[int] = None,
        system_code: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[PermissionMatrix], int]:
        query = db.query(PermissionMatrix)
        if position_id:
            query = query.filter(PermissionMatrix.position_id == position_id)
        if system_code:
            query = query.filter(PermissionMatrix.system_code == system_code)
        return cls._paginate(query.order_by(PermissionMatrix.id.desc()), page, page_size)

    @classmethod
    def delete_permission_matrix(cls, db: Session, matrix_id: int, operator_name: str = "system") -> bool:
        matrix = db.query(PermissionMatrix).get(matrix_id)
        if not matrix:
            return False
        db.delete(matrix)
        db.commit()
        return True

    @classmethod
    def list_snapshots(
        cls,
        db: Session,
        user_id: Optional[int] = None,
        system_code: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[PermissionSnapshot], int]:
        query = db.query(PermissionSnapshot)
        if user_id:
            query = query.filter(PermissionSnapshot.user_id == user_id)
        if system_code:
            query = query.filter(PermissionSnapshot.system_code == system_code)
        return cls._paginate(query.order_by(PermissionSnapshot.created_at.desc()), page, page_size)

    @classmethod
    def list_deviations(
        cls,
        db: Session,
        user_id: Optional[int] = None,
        system_code: Optional[str] = None,
        risk_level: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[PermissionDeviation], int]:
        query = db.query(PermissionDeviation)
        if user_id:
            query = query.filter(PermissionDeviation.user_id == user_id)
        if system_code:
            query = query.filter(PermissionDeviation.system_code == system_code)
        if risk_level:
            query = query.filter(PermissionDeviation.risk_level == risk_level)
        if status:
            query = query.filter(PermissionDeviation.status == status)
        return cls._paginate(query.order_by(PermissionDeviation.created_at.desc()), page, page_size)

    @classmethod
    def list_audit_logs(
        cls,
        db: Session,
        user_id: Optional[int] = None,
        action: Optional[str] = None,
        target_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[AuditLog], int]:
        query = db.query(AuditLog)
        if user_id:
            query = query.filter(AuditLog.user_id == user_id)
        if action:
            query = query.filter(AuditLog.action.like(f"%{action}%"))
        if target_type:
            query = query.filter(AuditLog.target_type == target_type)
        if start_date:
            query = query.filter(AuditLog.created_at >= start_date)
        if end_date:
            query = query.filter(AuditLog.created_at <= end_date)
        return cls._paginate(query.order_by(AuditLog.created_at.desc()), page, page_size)

    @classmethod
    def init_sample_data(cls, db: Session) -> Dict[str, int]:
        count_users = db.query(User).count()
        if count_users > 0:
            logger.info("已存在数据，跳过初始化示例数据")
            return {"message": "data_exists"}

        positions_data = [
            {"name": "系统管理员", "code": "SYS_ADMIN", "department": "信息部", "description": "负责系统运维管理"},
            {"name": "财务经理", "code": "FIN_MANAGER", "department": "财务部", "description": "负责财务部门管理"},
            {"name": "财务专员", "code": "FIN_STAFF", "department": "财务部", "description": "日常财务处理"},
            {"name": "销售经理", "code": "SALES_MANAGER", "department": "销售部", "description": "负责销售团队管理"},
            {"name": "销售专员", "code": "SALES_STAFF", "department": "销售部", "description": "日常销售工作"},
            {"name": "采购专员", "code": "PUR_STAFF", "department": "采购部", "description": "日常采购工作"},
            {"name": "安全管理员", "code": "SEC_ADMIN", "department": "信息部", "description": "负责安全审计与权限管理"},
            {"name": "安全总监", "code": "SEC_DIRECTOR", "department": "信息部", "description": "负责安全策略决策"},
            {"name": "人力资源专员", "code": "HR_STAFF", "department": "人事部", "description": "人力资源日常工作"},
            {"name": "普通员工", "code": "EMPLOYEE", "department": "通用", "description": "普通员工岗位"},
        ]

        created_positions = []
        for pos_data in positions_data:
            pos = Position(**pos_data)
            db.add(pos)
            created_positions.append(pos)
        db.flush()

        pos_map = {p.code: p.id for p in created_positions}

        users_data = [
            {"username": "admin", "email": "admin@company.com", "full_name": "超级管理员", "position_id": pos_map["SYS_ADMIN"], "department": "信息部", "role": "admin"},
            {"username": "sec_admin", "email": "sec_admin@company.com", "full_name": "李安全", "position_id": pos_map["SEC_ADMIN"], "department": "信息部", "role": "security_admin"},
            {"username": "sec_director", "email": "sec_dir@company.com", "full_name": "王总监", "position_id": pos_map["SEC_DIRECTOR"], "department": "信息部", "role": "security_director"},
            {"username": "fin_mgr", "email": "fin_mgr@company.com", "full_name": "陈财务", "position_id": pos_map["FIN_MANAGER"], "department": "财务部", "role": "manager"},
            {"username": "fin_zhang", "email": "fin_zhang@company.com", "full_name": "张会计", "position_id": pos_map["FIN_STAFF"], "department": "财务部", "role": "user"},
            {"username": "fin_li", "email": "fin_li@company.com", "full_name": "李出纳", "position_id": pos_map["FIN_STAFF"], "department": "财务部", "role": "user"},
            {"username": "sales_mgr", "email": "sales_mgr@company.com", "full_name": "赵销售", "position_id": pos_map["SALES_MANAGER"], "department": "销售部", "role": "manager"},
            {"username": "sales_wang", "email": "sales_wang@company.com", "full_name": "王业务", "position_id": pos_map["SALES_STAFF"], "department": "销售部", "role": "user"},
            {"username": "sales_liu", "email": "sales_liu@company.com", "full_name": "刘顾问", "position_id": pos_map["SALES_STAFF"], "department": "销售部", "role": "user"},
            {"username": "pur_chen", "email": "pur_chen@company.com", "full_name": "陈采购", "position_id": pos_map["PUR_STAFF"], "department": "采购部", "role": "user"},
            {"username": "hr_zhao", "email": "hr_zhao@company.com", "full_name": "赵人事", "position_id": pos_map["HR_STAFF"], "department": "人事部", "role": "user"},
            {"username": "emp_sun", "email": "sun@company.com", "full_name": "孙普通", "position_id": pos_map["EMPLOYEE"], "department": "运营部", "role": "user"},
            {"username": "emp_zhou", "email": "zhou@company.com", "full_name": "周员工", "position_id": pos_map["EMPLOYEE"], "department": "市场部", "role": "user"},
            {"username": "emp_wu", "email": "wu@company.com", "full_name": "吴试用", "position_id": pos_map["EMPLOYEE"], "department": "产品部", "role": "user"},
            {"username": "emp_zheng", "email": "zheng@company.com", "full_name": "郑新", "position_id": pos_map["EMPLOYEE"], "department": "技术部", "role": "user"},
        ]

        for user_data in users_data:
            user = User(**user_data)
            db.add(user)
        db.flush()

        matrix_rules = {
            "SYS_ADMIN": {
                "ERP": ["erp:view:finance", "erp:edit:order", "erp:approve:payment", "erp:view:inventory", "erp:manage:supplier", "erp:delete:order", "erp:export:report", "erp:manage:user"],
                "OA": ["oa:view:notice", "oa:edit:notice", "oa:approve:leave", "oa:view:attendance", "oa:manage:department", "oa:initiate:process"],
                "CRM": ["crm:view:customer", "crm:edit:customer", "crm:view:contract", "crm:approve:discount", "crm:delete:customer", "crm:export:customer"],
                "FINANCE": ["finance:view:voucher", "finance:edit:voucher", "finance:approve:voucher", "finance:view:budget", "finance:manage:account", "finance:close:period"],
            },
            "FIN_MANAGER": {
                "ERP": ["erp:view:finance", "erp:view:inventory", "erp:manage:supplier", "erp:export:report"],
                "OA": ["oa:view:notice", "oa:approve:leave", "oa:view:attendance", "oa:initiate:process"],
                "CRM": ["crm:view:customer", "crm:view:contract", "crm:approve:discount", "crm:export:customer"],
                "FINANCE": ["finance:view:voucher", "finance:edit:voucher", "finance:approve:voucher", "finance:view:budget", "finance:manage:account", "finance:close:period"],
            },
            "FIN_STAFF": {
                "ERP": ["erp:view:finance", "erp:edit:order", "erp:view:inventory", "erp:export:report"],
                "OA": ["oa:view:notice", "oa:view:attendance", "oa:initiate:process"],
                "CRM": ["crm:view:customer", "crm:view:contract"],
                "FINANCE": ["finance:view:voucher", "finance:edit:voucher", "finance:view:budget"],
            },
            "SALES_MANAGER": {
                "ERP": ["erp:view:inventory", "erp:edit:order", "erp:view:finance", "erp:export:report"],
                "OA": ["oa:view:notice", "oa:approve:leave", "oa:view:attendance", "oa:initiate:process"],
                "CRM": ["crm:view:customer", "crm:edit:customer", "crm:view:contract", "crm:approve:discount", "crm:export:customer"],
                "FINANCE": ["finance:view:budget"],
            },
            "SALES_STAFF": {
                "ERP": ["erp:view:inventory", "erp:edit:order"],
                "OA": ["oa:view:notice", "oa:view:attendance", "oa:initiate:process"],
                "CRM": ["crm:view:customer", "crm:edit:customer", "crm:view:contract"],
                "FINANCE": [],
            },
            "PUR_STAFF": {
                "ERP": ["erp:view:inventory", "erp:manage:supplier", "erp:edit:order", "erp:view:finance"],
                "OA": ["oa:view:notice", "oa:view:attendance", "oa:initiate:process"],
                "CRM": [],
                "FINANCE": ["finance:view:voucher"],
            },
            "SEC_ADMIN": {
                "ERP": ["erp:view:finance", "erp:view:inventory", "erp:export:report"],
                "OA": ["oa:view:notice", "oa:view:attendance", "oa:manage:department", "oa:initiate:process"],
                "CRM": ["crm:view:customer", "crm:view:contract", "crm:export:customer"],
                "FINANCE": ["finance:view:voucher", "finance:view:budget"],
            },
            "SEC_DIRECTOR": {
                "ERP": ["erp:view:finance", "erp:view:inventory", "erp:manage:supplier", "erp:export:report"],
                "OA": ["oa:view:notice", "oa:edit:notice", "oa:approve:leave", "oa:view:attendance", "oa:manage:department", "oa:initiate:process"],
                "CRM": ["crm:view:customer", "crm:edit:customer", "crm:view:contract", "crm:approve:discount", "crm:export:customer"],
                "FINANCE": ["finance:view:voucher", "finance:approve:voucher", "finance:view:budget", "finance:manage:account"],
            },
            "HR_STAFF": {
                "ERP": [],
                "OA": ["oa:view:notice", "oa:edit:notice", "oa:approve:leave", "oa:view:attendance", "oa:initiate:process"],
                "CRM": [],
                "FINANCE": [],
            },
            "EMPLOYEE": {
                "ERP": ["erp:view:inventory"],
                "OA": ["oa:view:notice", "oa:view:attendance", "oa:initiate:process"],
                "CRM": ["crm:view:customer"],
                "FINANCE": [],
            },
        }

        from app.services.snapshot_service import SnapshotSyncService

        matrix_count = 0
        for pos_code, systems in matrix_rules.items():
            pos_id = pos_map.get(pos_code)
            if not pos_id:
                continue
            for sys_code, perm_codes in systems.items():
                perms_info = SnapshotSyncService.MOCK_PERMISSIONS.get(sys_code, [])
                for perm_info in perms_info:
                    if perm_info["code"] in perm_codes:
                        matrix = PermissionMatrix(
                            position_id=pos_id,
                            system_code=sys_code,
                            permission_code=perm_info["code"],
                            permission_name=perm_info["name"],
                            permission_type=perm_info["type"],
                            is_required=True,
                        )
                        db.add(matrix)
                        matrix_count += 1

        db.commit()

        result = {
            "positions": len(created_positions),
            "users": len(users_data),
            "permission_matrix": matrix_count,
        }
        logger.info(f"示例数据初始化完成: {result}")
        return result
