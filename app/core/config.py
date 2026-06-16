from typing import List
from pydantic_settings import BaseSettings
from pydantic import Field
import os


class Settings(BaseSettings):
    APP_NAME: str = "权限合规审计系统"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    PROJECT_ROOT: str = os.path.dirname(os.path.dirname(BASE_DIR))
    LOG_DIR: str = os.path.join(PROJECT_ROOT, "logs")
    EXPORT_DIR: str = os.path.join(PROJECT_ROOT, "exports")

    DATABASE_URL: str = Field(
        default="sqlite:///./permission_audit.db",
        env="DATABASE_URL"
    )

    SECRET_KEY: str = Field(default="your-secret-key-change-in-production", env="SECRET_KEY")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    UPGRADE_HOURS: int = 48
    CRON_DAILY_SYNC: str = "0 2 * * *"
    CRON_DAILY_REPORT: str = "0 3 * * *"
    CRON_CHECK_UPGRADE: str = "0 * * * *"

    BUSINESS_SYSTEMS: List[dict] = [
        {"name": "ERP系统", "code": "ERP", "importance": 5, "api_url": "http://erp.example.com/api"},
        {"name": "OA系统", "code": "OA", "importance": 3, "api_url": "http://oa.example.com/api"},
        {"name": "CRM系统", "code": "CRM", "importance": 4, "api_url": "http://crm.example.com/api"},
        {"name": "财务系统", "code": "FINANCE", "importance": 5, "api_url": "http://finance.example.com/api"},
    ]

    DINGTALK_WEBHOOK: str = Field(default="", env="DINGTALK_WEBHOOK")
    WECHAT_WEBHOOK: str = Field(default="", env="WECHAT_WEBHOOK")

    HIGH_RISK_THRESHOLD: int = 80
    MEDIUM_RISK_THRESHOLD: int = 50

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

os.makedirs(settings.LOG_DIR, exist_ok=True)
os.makedirs(settings.EXPORT_DIR, exist_ok=True)
