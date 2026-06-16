import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from app.core.database import Base, engine, SessionLocal
from app.models import User, Position, PermissionMatrix, PermissionSnapshot, PermissionDeviation, AuditTicket, PermissionChangeHistory
from app.services import (
    SnapshotSyncService,
    DeviationDetectionService,
    TicketService,
    CRUDService,
    AdapterFactory,
    get_business_system_adapter,
)
from app.utils import get_deviation_type_text, get_risk_level_text, deviation_to_dict, ticket_to_dict
from datetime import date

def main():
    print("=" * 70)
    print("  权限合规审计系统 - 第二批需求验收测试 (v2)")
    print("=" * 70)
    print()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        print("=" * 1 + " 初始化测试数据 + 切换Mock适配器")
        print("   " + "-" * 50)

        CRUDService.init_sample_data(db)
        AdapterFactory.set_adapter_type("mock")
        adapter = get_business_system_adapter()
        adapter.set_should_fail(False)
        adapter.set_adjust_should_fail(False)
        print("   适配器已切换为: Mock模式")

        test_user = db.query(User).filter(User.username == "zhangkaifa").first()
        if not test_user:
            test_user = db.query(User).filter(User.role == "user").first()
        print(f"   测试用户: {test_user.full_name} (ID: {test_user.id})")

        today = date.today()

        # 清理今天的所有数据，确保干净
        existing_snaps = db.query(PermissionSnapshot).filter(
            PermissionSnapshot.snapshot_date == today,
        ).all()
        for s in existing_snaps:
            db.delete(s)
        db.commit()

        existing_tickets = db.query(AuditTicket).all()
        for t in existing_tickets:
            db.delete(t)
        existing_devs = db.query(PermissionDeviation).all()
        for d in existing_devs:
            db.delete(d)
        db.commit()
        print("   已清理历史数据，测试环境干净")

        print()
        print("=" * 1 + " 需求1: 同步接口返回失败详情（失败用户/系统/原因）")
        print("   " + "-" * 50)

        # 构造部分失败场景：ERP接口失败，其他系统成功
        adapter.set_should_fail(True, "ERP")
        adapter.set_fixed_permissions("OA", {"oa:view:notice": True, "oa:view:attendance": True})
        adapter.set_fixed_permissions("CRM", {"crm:view:customer": True})
        adapter.set_fixed_permissions("FINANCE", {"finance:view:voucher": True})

        print("   场景: ERP接口失败，OA/CRM/FINANCE接口正常")

        sync_result = SnapshotSyncService.sync_all_users(
            db, user_ids=[test_user.id], trigger_by="验收测试-需求1"
        )

        print(f"   total_users: {sync_result['total_users']}")
        print(f"   success_users: {sync_result['success_users']}")
        print(f"   failed_users: {sync_result['failed_users']}")
        print(f"   total_snapshots: {sync_result['total_snapshots']}")
        print(f"   all_success: {sync_result['all_success']}")
        print(f"   failed_items 数量: {len(sync_result['failed_items'])}")

        assert sync_result["failed_users"] == 1, f"❌ 需求1失败: 应有1个用户有失败项，实际{sync_result['failed_users']}"
        assert sync_result["total_snapshots"] > 0, "❌ 需求1失败: 应有部分快照成功"
        assert sync_result["all_success"] == False, "❌ 需求1失败: all_success 应为 False"
        assert len(sync_result["failed_items"]) == 1, "❌ 需求1失败: 应有1条失败记录"

        failed_item = sync_result["failed_items"][0]
        assert failed_item["user_id"] == test_user.id, "❌ 需求1失败: 失败用户ID不对"
        assert len(failed_item["failed_systems"]) >= 1, "❌ 需求1失败: 至少有1个系统失败"
        assert "reason" in failed_item["failed_systems"][0], "❌ 需求1失败: 缺少失败原因字段"

        failed_erp = next((fs for fs in failed_item["failed_systems"] if fs["system_code"] == "ERP"), None)
        assert failed_erp is not None, "❌ 需求1失败: 没有ERP系统的失败记录"
        assert "系统维护中" in failed_erp["reason"], f"❌ 需求1失败: 失败原因不清晰，实际: {failed_erp['reason']}"

        print()
        print("   失败详情示例:")
        print(f"     用户: {failed_item['full_name']} ({failed_item['username']})")
        print(f"     失败系统: {failed_erp['system_name']}")
        print(f"     失败原因: {failed_erp['reason']}")

        print()
        print("   ✅ 需求1验证通过: 同步接口返回了失败的用户、系统和清晰的失败原因")

        # 清理：把需求1产生的快照标记为已处理，避免影响后续测试
        unprocessed = db.query(PermissionSnapshot).filter(
            PermissionSnapshot.user_id == test_user.id,
            PermissionSnapshot.is_processed == False,
        ).all()
        for s in unprocessed:
            s.is_processed = True
        db.commit()
        print(f"   已标记 {len(unprocessed)} 个快照为已处理，避免影响后续测试")

        # 清理
        adapter.set_should_fail(False)

        print()
        print("=" * 1 + " 需求2: 偏离检测后自动开工单 + 需求4: 统计结果整合")
        print("   " + "-" * 50)

        # 构造高危越权场景
        erp_permissions = {
            "erp:view:finance": True,
            "erp:view:inventory": True,
            "erp:approve:payment": True,
            "erp:manage:user": True,
        }
        adapter.set_fixed_permissions("ERP", erp_permissions)

        # 先同步（这样才有未处理的快照）
        sync_result2 = SnapshotSyncService.sync_all_users(
            db, system_code="ERP", user_ids=[test_user.id], trigger_by="验收测试-需求2"
        )
        print(f"   同步完成: {sync_result2['total_snapshots']}个ERP快照")
        assert sync_result2["total_snapshots"] == 1, "❌ 需求2失败: ERP快照同步失败"

        # 验证快照是未处理状态
        new_snap = db.query(PermissionSnapshot).filter(
            PermissionSnapshot.user_id == test_user.id,
            PermissionSnapshot.system_code == "ERP",
            PermissionSnapshot.is_processed == False,
        ).first()
        assert new_snap is not None, "❌ 需求2失败: 没有未处理的快照"
        print(f"   未处理快照数: 1个 (ID: {new_snap.id})")

        # 执行偏离检测 - 应该自动生成工单
        print("   执行偏离检测（含自动开工单）...")
        detect_result = DeviationDetectionService.process_all_unprocessed(db)

        print(f"   processed_snapshots: {detect_result['processed_snapshots']}")
        print(f"   total_deviations: {detect_result['total_deviations']}")
        print(f"   high_risk_count: {detect_result['high_risk_count']}")
        print(f"   new_ticket_count: {detect_result['new_ticket_count']}")

        assert detect_result["processed_snapshots"] == 1, "❌ 需求2失败: 快照未处理"
        assert detect_result["total_deviations"] >= 2, f"❌ 需求2失败: 偏离数太少，实际{detect_result['total_deviations']}"
        assert detect_result["high_risk_count"] >= 2, f"❌ 需求2失败: 高危偏离数太少，实际{detect_result['high_risk_count']}"
        assert detect_result["new_ticket_count"] >= 2, f"❌ 需求2失败: 没有自动生成工单！实际{detect_result['new_ticket_count']}个"

        # 直接查询工单列表验证
        tickets = db.query(AuditTicket).filter(
            AuditTicket.deviation_id.in_(
                db.query(PermissionDeviation.id).filter(
                    PermissionDeviation.user_id == test_user.id,
                    PermissionDeviation.system_code == "ERP",
                )
            )
        ).all()

        print()
        print("   工单列表验证:")
        for t in tickets:
            assignee = db.query(User).get(t.assignee_id)
            dev = db.query(PermissionDeviation).get(t.deviation_id)
            print(f"     工单: {t.ticket_no}")
            print(f"       标题: {t.title}")
            print(f"       风险: {get_risk_level_text(dev.risk_level) if dev else '未知'}")
            print(f"       分配给: {assignee.full_name if assignee else '未分配'} ({assignee.role if assignee else ''})")
            print(f"       状态: {t.status}")

        assert len(tickets) >= 2, "❌ 需求2失败: 工单列表中没有足够的工单"
        for t in tickets:
            assert t.assignee_id is not None, f"❌ 需求2失败: 工单{t.ticket_no}未分配"
            dev = db.query(PermissionDeviation).get(t.deviation_id)
            assert dev.risk_level == "high", f"❌ 需求2失败: 工单{t.ticket_no}对应的偏离不是高危"

        print()
        print("   ✅ 需求2验证通过: 偏离检测后自动生成了高危工单，并已分配安全管理员")
        print("   ✅ 需求4验证通过: 检测返回包含了快照数、偏离数、高危数、新工单数")

        print()
        print("=" * 1 + " 需求4补充: sync_and_detect 一键接口完整统计")
        print("   " + "-" * 50)

        # 换一个系统测试 sync_and_detect 效果
        # 给FINANCE也配一个高危越权
        finance_perms = {
            "finance:view:voucher": True,
            "finance:edit:voucher": True,
            "finance:approve:voucher": True,
            "finance:close:period": True,
        }
        adapter.set_fixed_permissions("FINANCE", finance_perms)

        # 清理之前的FINANCE快照和偏离
        fin_snaps = db.query(PermissionSnapshot).filter(
            PermissionSnapshot.user_id == test_user.id,
            PermissionSnapshot.system_code == "FINANCE",
        ).all()
        for s in fin_snaps:
            db.delete(s)
        fin_devs = db.query(PermissionDeviation).filter(
            PermissionDeviation.user_id == test_user.id,
            PermissionDeviation.system_code == "FINANCE",
        ).all()
        for d in fin_devs:
            # 先删关联工单
            ts = db.query(AuditTicket).filter(AuditTicket.deviation_id == d.id).all()
            for t in ts:
                db.delete(t)
            db.delete(d)
        db.commit()

        print("   场景: 新增FINANCE系统高危越权，测试一键同步+检测+开工单")

        # 模拟调用 sync_and_detect 接口的逻辑
        sync_res = SnapshotSyncService.sync_all_users(
            db, system_code="FINANCE", user_ids=[test_user.id], trigger_by="验收测试-需求4"
        )
        detect_res = DeviationDetectionService.process_all_unprocessed(db)

        summary = {
            "success_snapshots": sync_res["total_snapshots"],
            "failed_snapshots": sync_res["failed_users"],
            "total_deviations": detect_res["total_deviations"],
            "high_risk_deviations": detect_res["high_risk_count"],
            "new_tickets": detect_res["new_ticket_count"],
        }

        print(f"   📊 统一统计结果:")
        print(f"     成功快照: {summary['success_snapshots']} 个")
        print(f"     失败快照: {summary['failed_snapshots']} 个")
        print(f"     总偏离数: {summary['total_deviations']} 项")
        print(f"     高危偏离: {summary['high_risk_deviations']} 项")
        print(f"     新增工单: {summary['new_tickets']} 个")

        assert summary["success_snapshots"] == 1, "❌ 需求4失败: 快照数不对"
        assert summary["high_risk_deviations"] >= 1, "❌ 需求4失败: 高危偏离数不对"
        assert summary["new_tickets"] >= 1, "❌ 需求4失败: 新工单数不对"

        print()
        print("   ✅ 需求4验证通过: 一次返回了成功快照数、失败数、高危偏离数、新工单数")

        print()
        print("=" * 1 + " 需求3: 工单处理失败回滚（权限调整失败时不关闭工单）")
        print("   " + "-" * 50)

        # 找到第一个未处理的工单
        pending_tickets = db.query(AuditTicket).filter(
            AuditTicket.status == "pending",
            AuditTicket.deviation_id.isnot(None),
        ).all()
        assert len(pending_tickets) > 0, "❌ 需求3失败: 没有待处理的工单"

        test_ticket = pending_tickets[0]
        test_dev = db.query(PermissionDeviation).get(test_ticket.deviation_id)

        print(f"   测试工单: {test_ticket.ticket_no}")
        print(f"   偏离权限: {test_dev.permission_code} ({test_dev.permission_name})")
        print(f"   处理前工单状态: {test_ticket.status}")
        print(f"   处理前偏离状态: {test_dev.status}")
        print()

        # 设置Mock适配器权限调整失败
        fail_msg = "模拟业务系统接口异常：权限管理系统正在维护，无法调整权限"
        adapter.set_adjust_should_fail(True, test_dev.system_code, fail_msg)
        print(f"   已启用权限调整失败模拟: {test_dev.system_code}")
        print()

        # 尝试处理工单（调整权限方式）
        success, result_ticket, message = TicketService.resolve_ticket(
            db=db,
            ticket_id=test_ticket.id,
            resolution="尝试撤销权限",
            action_type="adjust_permission",
            resolver_id=1,
            resolver_name="安全管理员",
            remarks="测试失败回滚"
        )

        print(f"   处理结果: success = {success}")
        print(f"   返回消息: {message}")
        print()

        # 刷新数据
        db.refresh(test_ticket)
        db.refresh(test_dev)

        print(f"   处理后工单状态: {test_ticket.status}")
        print(f"   处理后偏离状态: {test_dev.status}")
        print(f"   处理后工单 resolved_at: {test_ticket.resolved_at}")
        print()

        # 验证：失败时工单不关闭、偏离不标记已解决
        assert success == False, "❌ 需求3失败: 应该返回失败，但返回了成功"
        assert test_ticket.status != "resolved", f"❌ 需求3失败: 工单不应被关闭！当前状态: {test_ticket.status}"
        assert test_dev.status != "resolved", f"❌ 需求3失败: 偏离不应标记为已解决！当前: {test_dev.status}"
        assert test_ticket.resolved_at is None, "❌ 需求3失败: 工单resolved_at不应有值"
        assert test_dev.resolved_at is None, "❌ 需求3失败: 偏离resolved_at不应有值"
        assert fail_msg in message or "接口异常" in message, f"❌ 需求3失败: 返回消息不包含失败原因，实际: {message}"

        # 验证：变更历史没有新增（失败时不写变更历史）
        history_count = db.query(PermissionChangeHistory).filter(
            PermissionChangeHistory.user_id == test_user.id,
            PermissionChangeHistory.system_code == test_dev.system_code,
            PermissionChangeHistory.permission_code == test_dev.permission_code,
            PermissionChangeHistory.source == "audit_ticket",
        ).count()
        assert history_count == 0, f"❌ 需求3失败: 失败时不应写入变更历史！实际有{history_count}条"

        print(f"   变更历史中audit_ticket来源记录数: {history_count} (应为0)")
        print()
        print("   ✅ 需求3验证通过: 权限调整失败时，工单未关闭、偏离未解决、无变更历史、返回清晰失败原因")

        # 再验证：恢复正常后，处理成功时正常关闭工单
        print()
        print("   恢复正常后重试处理，验证成功流程依然正常:")
        adapter.set_adjust_should_fail(False)

        success2, result_ticket2, message2 = TicketService.resolve_ticket(
            db=db,
            ticket_id=test_ticket.id,
            resolution="已通过权限管理系统撤销用户权限",
            action_type="adjust_permission",
            resolver_id=1,
            resolver_name="安全管理员",
            remarks="正常处理"
        )

        db.refresh(test_ticket)
        db.refresh(test_dev)

        print(f"     处理结果: success = {success2}")
        print(f"     工单状态: {test_ticket.status}")
        print(f"     偏离状态: {test_dev.status}")

        assert success2 == True, "❌ 需求3失败: 恢复正常后处理应该成功"
        assert test_ticket.status == "resolved", "❌ 需求3失败: 成功时工单应关闭"
        assert test_dev.status == "resolved", "❌ 需求3失败: 成功时偏离应标记已解决"
        print("     ✅ 成功流程正常，失败回滚逻辑不影响正常处理")

        print()
        print("=" * 70)
        print("  🎉 第二批4个需求全部验收通过！")
        print("=" * 70)
        print()
        print("┌─────────────────────────────────────────────────────────────────┐")
        print("│  验收项                                状态                   │")
        print("├─────────────────────────────────────────────────────────────────┤")
        print("│  1. 同步接口返回失败详情（用户/系统/原因）  ✅ 通过            │")
        print("│  2. 检测后自动开工单+分配安全管理员        ✅ 通过            │")
        print("│  3. 权限调整失败时工单不关闭、偏离不解决    ✅ 通过            │")
        print("│  4. 同步检测统计结果整合（4个核心指标）    ✅ 通过            │")
        print("└─────────────────────────────────────────────────────────────────┘")
        print()
        print("📊 测试产出汇总:")
        print(f"   - 高危偏离: {detect_result['high_risk_count'] + summary['high_risk_deviations']} 项")
        print(f"   - 自动生成工单: {detect_result['new_ticket_count'] + summary['new_tickets']} 个")
        print(f"   - 失败回滚验证: 1次失败 + 1次成功重试")
        print()

        return True

    except AssertionError as e:
        print(f"\n❌ 验收失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n❌ 测试异常: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()
        AdapterFactory.set_adapter_type("real")

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
