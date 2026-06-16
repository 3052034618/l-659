from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.database import engine, Base, SessionLocal
from app.routes.system_routes import router as system_router
from app.routes.sync_routes import router as sync_router
from app.routes.ticket_routes import router as ticket_router
from app.routes.audit_routes import router as audit_router
from app.routes.report_routes import router as report_router
from app.routes.audit_batch_routes import router as audit_batch_router
from app.utils import logger
from app.services import SchedulerService, CRUDService
from app.models import *


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"正在启动 {settings.APP_NAME} v{settings.APP_VERSION}...")

    Base.metadata.create_all(bind=engine)
    logger.info("数据库表结构初始化完成")

    db = SessionLocal()
    try:
        CRUDService.init_sample_data(db)
    except Exception as e:
        logger.warning(f"初始化示例数据失败: {str(e)}")
    finally:
        db.close()

    SchedulerService.init_scheduler()
    logger.info("定时任务调度器启动完成")

    logger.info(f"{settings.APP_NAME} 启动成功！")
    yield

    SchedulerService.shutdown_scheduler()
    logger.info(f"{settings.APP_NAME} 已关闭")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="""
# 权限合规审计系统 API

## 功能模块

### 1. 基础数据管理
- 用户、岗位、权限矩阵（标准权限）的增删改查

### 2. 权限同步与偏离检测
- 从各业务系统同步用户权限快照
- 与岗位标准权限矩阵逐项比对
- 自动标记权限偏离（过高/过低）
- 根据系统重要性和偏离程度计算风险等级

### 3. 审计工单管理
- 高风险偏离自动生成审计工单
- 分配安全管理员处理
- 超48小时未处理自动升级至安全总监
- 审计员确认后自动调整权限或更新风险标记

### 4. 专项审计与变更历史
- 管理员手动发起专项权限审计
- 自动汇总关联系统的权限变更历史
- 支持按用户/系统维度查询变更记录

### 5. 合规报告
- 每天凌晨自动生成权限合规报告
- 统计各系统权限偏离数、平均修复时长、审计完成率
- 支持导出 PDF 和 Excel 格式

### 6. 任务调度与预警
- 所有操作记录详细审计日志
- 高危偏离实时推送预警到安全群
- 支持手动触发定时任务
        """,
        contact={
            "name": "安全管理团队",
            "email": "security@company.com",
        },
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", tags=["系统"], summary="健康检查")
    def root():
        return {
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "running",
            "docs": "/docs",
            "upgrade_hours": settings.UPGRADE_HOURS,
        }

    @app.get("/health", tags=["系统"], summary="健康状态检查")
    def health_check():
        return {"status": "healthy", "timestamp": __import__("datetime").datetime.now().isoformat()}

    app.include_router(system_router)
    app.include_router(sync_router)
    app.include_router(ticket_router)
    app.include_router(audit_router)
    app.include_router(report_router)
    app.include_router(audit_batch_router)

    return app


app = create_app()
