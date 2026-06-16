from fastapi import APIRouter
from app.routes.system_routes import router as system_router
from app.routes.sync_routes import router as sync_router
from app.routes.ticket_routes import router as ticket_router
from app.routes.audit_routes import router as audit_router
from app.routes.report_routes import router as report_router

api_router = APIRouter()

api_router.include_router(system_router)
api_router.include_router(sync_router)
api_router.include_router(ticket_router)
api_router.include_router(audit_router)
api_router.include_router(report_router)

__all__ = ["api_router"]
