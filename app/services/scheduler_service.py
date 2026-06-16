from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from typing import Optional
import atexit

from app.core.config import settings
from app.core.database import SessionLocal
from app.utils import logger
from app.services.snapshot_service import SnapshotSyncService
from app.services.deviation_service import DeviationDetectionService
from app.services.ticket_service import TicketService
from app.services.report_service import ReportService


class SchedulerService:
    _scheduler: Optional[BackgroundScheduler] = None

    @classmethod
    def get_scheduler(cls) -> BackgroundScheduler:
        if cls._scheduler is None:
            cls._scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        return cls._scheduler

    @classmethod
    def daily_sync_task(cls):
        logger.info("===== 开始执行每日权限快照同步任务 =====")
        start_time = datetime.now()
        db = SessionLocal()
        try:
            result = SnapshotSyncService.sync_all_users(db, trigger_by="scheduled_daily")
            logger.info(f"快照同步结果: {result}")

            detection_result = DeviationDetectionService.process_all_unprocessed(db)
            logger.info(f"偏离检测结果: {detection_result}")

            tickets = TicketService.auto_generate_tickets(db)
            logger.info(f"自动生成工单数: {len(tickets)}")

        except Exception as e:
            logger.error(f"每日同步任务执行异常: {str(e)}", exc_info=True)
        finally:
            db.close()

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"===== 每日权限快照同步任务完成，耗时 {elapsed:.1f} 秒 =====")

    @classmethod
    def daily_report_task(cls):
        logger.info("===== 开始执行每日合规报告生成任务 =====")
        start_time = datetime.now()
        db = SessionLocal()
        try:
            report = ReportService.generate_daily_report(db, operator_name="scheduled_daily")
            logger.info(
                f"报告生成完成: {report.report_date}, "
                f"偏离总数: {report.total_deviations}, "
                f"完成率: {report.audit_completion_rate}%"
            )
        except Exception as e:
            logger.error(f"每日报告任务执行异常: {str(e)}", exc_info=True)
        finally:
            db.close()

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"===== 每日合规报告生成任务完成，耗时 {elapsed:.1f} 秒 =====")

    @classmethod
    def ticket_upgrade_check_task(cls):
        db = SessionLocal()
        try:
            upgraded = TicketService.check_and_upgrade_tickets(db)
            if upgraded:
                logger.info(f"工单升级检查完成，升级 {len(upgraded)} 个工单")
        except Exception as e:
            logger.error(f"工单升级检查任务异常: {str(e)}", exc_info=True)
        finally:
            db.close()

    @classmethod
    def init_scheduler(cls):
        scheduler = cls.get_scheduler()

        if scheduler.running:
            logger.info("调度器已在运行")
            return

        scheduler.add_job(
            cls.daily_sync_task,
            trigger=CronTrigger.from_crontab(settings.CRON_DAILY_SYNC),
            id="daily_permission_sync",
            name="每日权限快照同步与偏离检测",
            replace_existing=True,
        )
        logger.info(f"已注册定时任务: 每日权限同步 [{settings.CRON_DAILY_SYNC}]")

        scheduler.add_job(
            cls.daily_report_task,
            trigger=CronTrigger.from_crontab(settings.CRON_DAILY_REPORT),
            id="daily_compliance_report",
            name="每日合规报告生成",
            replace_existing=True,
        )
        logger.info(f"已注册定时任务: 每日报告生成 [{settings.CRON_DAILY_REPORT}]")

        scheduler.add_job(
            cls.ticket_upgrade_check_task,
            trigger=CronTrigger.from_crontab(settings.CRON_CHECK_UPGRADE),
            id="ticket_upgrade_check",
            name="工单超时升级检查",
            replace_existing=True,
        )
        logger.info(f"已注册定时任务: 工单升级检查 [{settings.CRON_CHECK_UPGRADE}]")

        scheduler.start()
        logger.info("调度器启动成功，注册任务数: %d", len(scheduler.get_jobs()))

        atexit.register(lambda: cls.shutdown_scheduler())

    @classmethod
    def shutdown_scheduler(cls):
        if cls._scheduler and cls._scheduler.running:
            cls._scheduler.shutdown(wait=False)
            logger.info("调度器已关闭")

    @classmethod
    def list_jobs(cls) -> list:
        scheduler = cls.get_scheduler()
        jobs = []
        for job in scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if job.next_run_time else None,
                "trigger": str(job.trigger),
            })
        return jobs

    @classmethod
    def trigger_job(cls, job_id: str) -> bool:
        scheduler = cls.get_scheduler()
        job = scheduler.get_job(job_id)
        if job:
            job.modify(next_run_time=datetime.now())
            logger.info(f"已手动触发任务: {job_id}")
            return True
        return False

    @classmethod
    def run_task_immediately(cls, task_name: str) -> dict:
        task_map = {
            "sync": cls.daily_sync_task,
            "report": cls.daily_report_task,
            "upgrade_check": cls.ticket_upgrade_check_task,
        }
        if task_name in task_map:
            start_time = datetime.now()
            task_map[task_name]()
            elapsed = (datetime.now() - start_time).total_seconds()
            return {"task": task_name, "elapsed_seconds": round(elapsed, 2), "status": "success"}
        return {"task": task_name, "status": "not_found"}
