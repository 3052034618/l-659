from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List

from app.core.database import get_db
from app.schemas import (
    UserCreate, UserUpdate, UserResponse,
    PositionCreate, PositionUpdate, PositionResponse,
    PermissionMatrixCreate, PermissionMatrixResponse,
    PaginatedResponse,
)
from app.services import CRUDService
from app.utils import logger

router = APIRouter(prefix="/api/v1/system", tags=["基础数据管理"])


@router.post("/users", response_model=UserResponse, summary="创建用户")
def create_user(data: UserCreate, db: Session = Depends(get_db)):
    try:
        return CRUDService.create_user(db, data, operator_name=data.username or "system")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"创建用户失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建用户失败: {str(e)}")


@router.put("/users/{user_id}", response_model=UserResponse, summary="更新用户")
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db)):
    user = CRUDService.update_user(db, user_id, data, operator_name="admin")
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.get("/users/{user_id}", response_model=UserResponse, summary="获取用户详情")
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = CRUDService.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.get("/users", summary="用户列表")
def list_users(
    position_id: Optional[int] = None,
    department: Optional[str] = None,
    is_active: Optional[bool] = None,
    keyword: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items, total = CRUDService.list_users(db, position_id, department, is_active, keyword, page, page_size)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.post("/positions", response_model=PositionResponse, summary="创建岗位")
def create_position(data: PositionCreate, db: Session = Depends(get_db)):
    try:
        return CRUDService.create_position(db, data, operator_name="admin")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"创建岗位失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建岗位失败: {str(e)}")


@router.put("/positions/{position_id}", response_model=PositionResponse, summary="更新岗位")
def update_position(position_id: int, data: PositionUpdate, db: Session = Depends(get_db)):
    position = CRUDService.update_position(db, position_id, data, operator_name="admin")
    if not position:
        raise HTTPException(status_code=404, detail="岗位不存在")
    return position


@router.get("/positions/{position_id}", response_model=PositionResponse, summary="获取岗位详情")
def get_position(position_id: int, db: Session = Depends(get_db)):
    position = CRUDService.get_position(db, position_id)
    if not position:
        raise HTTPException(status_code=404, detail="岗位不存在")
    return position


@router.get("/positions", summary="岗位列表")
def list_positions(
    department: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items, total = CRUDService.list_positions(db, department, keyword, page, page_size)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.post("/permission-matrix", response_model=PermissionMatrixResponse, summary="创建权限矩阵")
def create_permission_matrix(data: PermissionMatrixCreate, db: Session = Depends(get_db)):
    try:
        return CRUDService.create_permission_matrix(db, data, operator_name="admin")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/permission-matrix", summary="权限矩阵列表")
def list_permission_matrix(
    position_id: Optional[int] = None,
    system_code: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    items, total = CRUDService.list_permission_matrix(db, position_id, system_code, page, page_size)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.delete("/permission-matrix/{matrix_id}", summary="删除权限矩阵项")
def delete_permission_matrix(matrix_id: int, db: Session = Depends(get_db)):
    result = CRUDService.delete_permission_matrix(db, matrix_id, operator_name="admin")
    if not result:
        raise HTTPException(status_code=404, detail="权限矩阵项不存在")
    return {"success": True, "message": "删除成功"}


@router.get("/business-systems", summary="获取业务系统列表")
def get_business_systems():
    from app.core.config import settings
    return {"items": settings.BUSINESS_SYSTEMS}
