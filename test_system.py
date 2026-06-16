import sys
import os
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.database import SessionLocal, Base, engine
from app.models import *
from app.services import (
    CRUDService,
    SnapshotSyncService,
    DeviationDetectionService,
    TicketService,
    SpecialAuditService,
    ReportService,
)
from app.utils import logger, get_system_name, get_deviation_type_text, get_risk_level_text


def run_full_test():
    print("=" * 70)
    print(f"  权限合规审计系统 - 全流程测试")
    print(f"  测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    db = SessionLocal()

    try:
        print("\n[1/8] 初始化数据库...")
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        print("  ✓ 数据库表结构重建完成")

        print("\n[2/8] 加载示例数据...")
        result = CRUDService.init_sample_data(db)
        if "message" in result:
            print(f"  - {result['message']}")
        else:
            print(f"  ✓ 创建岗位: {result.get('positions', 0)} 个")
            print(f"  ✓ 创建用户: {result.get('users', 0)} 个")
            print(f"  ✓ 创建权限矩阵: {result.get('permission_matrix', 0)} 条")

        user_count = db.query(User).count()
        position_count = db.query(Position).count()
        matrix_count = db.query(PermissionMatrix).count()
        print(f"  ✓ 数据库统计: 用户{user_count}人, 岗位{position_count}个, 权限矩阵{matrix_count}条")

        print("\n[3/8] 同步所有用户权限快照...")
        sync_result = SnapshotSyncService.sync_all_users(db, trigger_by="test_script")
        print(f"  ✓ 同步用户数: {sync_result.get('success_users', 0)} / {sync_result.get('total_users', 0)}")
        print(f"  ✓ 生成快照数: {sync_result.get('total_snapshots', 0)} 个")

        snapshot_count = db.query(PermissionSnapshot).count()
        history_count = db.query(PermissionChangeHistory).count()
        print(f"  ✓ 快照总计: {snapshot_count} 个")
        if history_count > 0:
            print(f"  ✓ 权限变更记录: {history_count} 条")

        print("\n[4/8] 执行权限偏离检测...")
        detection_result = DeviationDetectionService.process_all_unprocessed(db)
        print(f"  ✓ 处理快照数: {detection_result.get('processed_snapshots', 0)} 个")
        print(f"  ✓ 检测偏离数: {detection_result.get('total_deviations', 0)} 项")
        print(f"  ✓ 高危偏离数: {detection_result.get('high_risk_count', 0)} 项")

        dev_count = db.query(PermissionDeviation).count()
        high_count = db.query(PermissionDeviation).filter(PermissionDeviation.risk_level == "high").count()
        medium_count = db.query(PermissionDeviation).filter(PermissionDeviation.risk_level == "medium").count()
        low_count = db.query(PermissionDeviation).filter(PermissionDeviation.risk_level == "low").count()
        excessive_count = db.query(PermissionDeviation).filter(PermissionDeviation.deviation_type == "excessive").count()
        deficient_count = db.query(PermissionDeviation).filter(PermissionDeviation.deviation_type == "deficient").count()

        print(f"\n  ===== 偏离统计 =====")
        print(f"  总计: {dev_count} 项")
        print(f"  风险分布: 高危{high_count}项, 中危{medium_count}项, 低危{low_count}项")
        print(f"  类型分布: 权限过高{excessive_count}项, 权限过低{deficient_count}项")

        print("\n[5/8] 自动生成审计工单...")
        tickets = TicketService.auto_generate_tickets(db)
        print(f"  ✓ 生成工单数: {len(tickets)} 个")

        ticket_count = db.query(AuditTicket).count()
        pending_tickets = db.query(AuditTicket).filter(AuditTicket.status == "pending").count()
        print(f"  ✓ 工单总计: {ticket_count} 个")
        print(f"  ✓ 待处理工单: {pending_tickets} 个")

        if tickets:
            print(f"\n  ===== 前5个工单预览 =====")
            for t in tickets[:5]:
                dev = db.query(PermissionDeviation).get(t.deviation_id)
                assignee = db.query(User).get(t.assignee_id)
                print(f"  [{t.ticket_no}] {get_risk_level_text(dev.risk_level)} - "
                      f"{t.title[:50]}... | 处理人: {assignee.username if assignee else '未分配'}")

        print("\n[6/8] 发起专项审计...")
        audit = SpecialAuditService.create_audit(
            db,
            title="全系统权限合规专项审计",
            audit_type="manual",
            target_user_ids=None,
            target_system_codes=None,
            initiator_id=1,
            initiator_name="test_script",
        )
        print(f"  ✓ 创建审计任务: [{audit.audit_no}] {audit.title}")

        audit_result = SpecialAuditService.run_audit(db, audit.id)
        print(f"  ✓ 审计完成: {audit_result.get('summary', '')}")
        data = audit_result.get("data", {})
        print(f"  - 权限偏离: {data.get('total_deviations', 0)} 项")
        print(f"  - 变更记录: {data.get('total_changes', 0)} 条")

        print("\n[7/8] 生成合规报告...")
        report = ReportService.generate_daily_report(db, operator_name="test_script")
        print(f"  ✓ 报告日期: {report.report_date}")
        print(f"  - 偏离总数: {report.total_deviations} 项")
        print(f"  - 高危: {report.high_risk_count} 项, 中危: {report.medium_risk_count} 项, 低危: {report.low_risk_count} 项")
        print(f"  - 已解决: {report.resolved_count} 项, 待处理: {report.pending_count} 项")
        print(f"  - 平均修复时长: {report.avg_fix_hours} 小时")
        print(f"  - 审计完成率: {report.audit_completion_rate}%")

        if report.pdf_path:
            print(f"  ✓ PDF报告: {report.pdf_path}")
        if report.excel_path:
            print(f"  ✓ Excel报告: {report.excel_path}")

        print("\n[8/8] 模拟工单处理...")
        pending = db.query(AuditTicket).filter(AuditTicket.status.in_(["pending", "processing"])).first()
        if pending:
            print(f"  ✓ 处理工单: [{pending.ticket_no}] {pending.title[:40]}...")
            resolved = TicketService.resolve_ticket(
                db,
                ticket_id=pending.id,
                resolution="已确认是误报，用户为临时项目成员，权限为项目期内临时授权，已在备注中说明",
                action_type="confirm_ignore",
                resolver_id=1,
                resolver_name="sec_admin",
                remarks="已与部门经理确认授权有效",
            )
            if resolved:
                print(f"  ✓ 工单已解决: {resolved.ticket_no}")

                dev = db.query(PermissionDeviation).get(resolved.deviation_id)
                if dev:
                    print(f"  ✓ 对应偏离状态: {dev.status}")

        log_count = db.query(AuditLog).count()
        print(f"\n  ✓ 审计日志总计: {log_count} 条")

        print("\n" + "=" * 70)
        print("  ✅ 全流程测试通过！所有核心功能正常运行")
        print("=" * 70)
        print(f"\n  📊 最终数据统计:")
        print(f"     - 用户: {db.query(User).count()} 人")
        print(f"     - 岗位: {db.query(Position).count()} 个")
        print(f"     - 权限矩阵: {db.query(PermissionMatrix).count()} 条")
        print(f"     - 权限快照: {db.query(PermissionSnapshot).count()} 个")
        print(f"     - 权限偏离: {db.query(PermissionDeviation).count()} 项")
        print(f"     - 审计工单: {db.query(AuditTicket).count()} 个")
        print(f"     - 变更记录: {db.query(PermissionChangeHistory).count()} 条")
        print(f"     - 合规报告: {db.query(ComplianceReport).count()} 份")
        print(f"     - 专项审计: {db.query(SpecialAudit).count()} 次")
        print(f"     - 操作日志: {db.query(AuditLog).count()} 条")
        print("\n  💡 启动服务: 运行 'uvicorn main:app --reload' 然后访问 http://localhost:8000/docs")

    except Exception as e:
        logger.error(f"测试执行异常: {str(e)}", exc_info=True)
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    run_full_test()
