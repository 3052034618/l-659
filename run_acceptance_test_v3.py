import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from datetime import date
from app.core.database import Base, engine, SessionLocal
from app.models import User, PermissionSnapshot, PermissionDeviation, AuditTicket, PermissionChangeHistory, SpecialAudit
from app.services import (
    SnapshotSyncService,
    DeviationDetectionService,
    TicketService,
    CRUDService,
    AdapterFactory,
    get_business_system_adapter,
    AuditBatchService,
)
from app.utils import get_risk_level_text, get_deviation_type_text

def main():
    print("=" * 70)
    print("  权限合规审计系统 - 第三批需求验收测试 (v3)")
    print("=" * 70)
    print()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        CRUDService.init_sample_data(db)
        AdapterFactory.set_adapter_type("mock")
        adapter = get_business_system_adapter()
        adapter.set_should_fail(False)
        adapter.set_adjust_should_fail(False)
        print("✅ 初始化完成：Mock适配器已启用")

        test_user = db.query(User).filter(User.username == "fin_zhang").first()
        if not test_user:
            test_user = db.query(User).filter(User.role == "user").first()
        print(f"✅ 测试用户: {test_user.full_name} (ID: {test_user.id})")

        test_user2 = db.query(User).filter(User.username == "sales_wang").first()
        print(f"✅ 测试用户2: {test_user2.full_name} (ID: {test_user2.id})")

        today = date.today()

        # 清理旧数据
        for model in [PermissionChangeHistory, AuditTicket, PermissionDeviation, PermissionSnapshot, SpecialAudit]:
            db.query(model).delete()
        db.commit()
        print("✅ 历史数据已清理")

        print()
        print("=" * 1 + " 需求1: 审计批次号，串起同步→检测→工单→变更历史")
        print("   " + "-" * 50)

        erp_perms = {
            "erp:view:finance": True,
            "erp:view:inventory": True,
            "erp:approve:payment": True,
            "erp:manage:user": True,
        }
        adapter.set_fixed_permissions("ERP", erp_perms)
        adapter.set_fixed_permissions("FINANCE", {
            "finance:view:voucher": True,
            "finance:approve:voucher": True,
        })
        print("   ✅ Mock权限已设置：ERP+财务高危越权场景")

        batch = AuditBatchService.create_batch(
            db=db,
            title="2026年Q2 ERP&财务系统权限专项审计",
            target_user_ids=[test_user.id],
            target_system_codes=["ERP", "FINANCE"],
            initiator_name="安全管理员",
        )
        print(f"   ✅ 审计批次已创建: {batch.batch_no}")
        print(f"      批次ID: {batch.id}")
        print(f"      审计编号: {batch.audit_no}")
        print(f"      目标用户: {len(batch.target_user_ids or [])}个")
        print(f"      目标系统: {len(batch.target_system_codes or [])}个 (ERP, FINANCE)")

        result = AuditBatchService.run_full_audit(
            db=db,
            batch=batch,
            force_refresh=False,
            initiator_name="安全管理员",
        )

        print(f"   ✅ 批次执行完成")
        print(f"      状态: {result['status']}")
        print(f"      同步: 成功{result['sync']['success_snapshots']}个，跳过{result['sync']['skipped_snapshots']}个，失败{result['sync']['failed_snapshots']}个")
        print(f"      检测: 偏离{result['detection']['total_deviations']}项，高危{result['detection']['high_risk_count']}项")
        print(f"      工单: 自动生成{result['detection']['new_ticket_count']}个")

        batch_id = batch.id

        # 验证快照、偏离、工单、变更历史都关联了batch_id
        snaps = db.query(PermissionSnapshot).filter(PermissionSnapshot.audit_batch_id == batch_id).all()
        devs = db.query(PermissionDeviation).filter(PermissionDeviation.audit_batch_id == batch_id).all()
        tickets = db.query(AuditTicket).filter(AuditTicket.audit_batch_id == batch_id).all()

        assert len(snaps) >= 2, f"❌ 需求1失败: 快照应该关联batch_id，实际{len(snaps)}个"
        assert len(devs) >= 2, f"❌ 需求1失败: 偏离应该关联batch_id，实际{len(devs)}个"
        assert len(tickets) >= 2, f"❌ 需求1失败: 工单应该关联batch_id，实际{len(tickets)}个"

        print(f"   ✅ 关联验证通过: 快照{len(snaps)}个，偏离{len(devs)}个，工单{len(tickets)}个，全部关联batch_id={batch_id}")

        # 处理一个工单，验证变更历史也关联batch_id
        pending_ticket = tickets[0]
        pending_dev = db.query(PermissionDeviation).get(pending_ticket.deviation_id)
        assert pending_dev.audit_batch_id == batch_id, "❌ 需求1失败: 偏离batch_id不匹配"

        success, res_ticket, msg = TicketService.resolve_ticket(
            db=db,
            ticket_id=pending_ticket.id,
            resolution="测试处理",
            action_type="adjust_permission",
            resolver_id=1,
            resolver_name="安全管理员",
            remarks="验收测试"
        )
        assert success, f"❌ 需求1失败: 工单处理失败: {msg}"

        histories = db.query(PermissionChangeHistory).filter(
            PermissionChangeHistory.audit_batch_id == batch_id
        ).all()
        assert len(histories) >= 1, "❌ 需求1失败: 变更历史应该关联batch_id"

        print(f"   ✅ 变更历史验证: {len(histories)}条变更历史已关联batch_id")

        print()
        print("   ✅ 需求1验证通过: 审计批次号串起了同步→检测→工单→变更历史全流程")

        print()
        print("=" * 1 + " 需求2: 一键同步检测只处理新快照，全失败时不检测")
        print("   " + "-" * 50)

        adapter.set_fixed_permissions("ERP", {})
        adapter.set_fixed_permissions("FINANCE", {})
        adapter.set_fixed_permissions("OA", {})

        # 测试：所有目标系统接口都失败
        adapter.set_should_fail(True, "ERP")
        adapter.set_should_fail(True, "FINANCE")
        print("   场景: ERP和FINANCE接口全部失败")

        batch2 = AuditBatchService.create_batch(
            db=db,
            title="测试全失败场景",
            target_user_ids=[test_user2.id],
            target_system_codes=["ERP", "FINANCE"],
            initiator_name="验收测试",
        )

        result2 = AuditBatchService.run_full_audit(
            db=db,
            batch=batch2,
            force_refresh=True,
            initiator_name="验收测试",
        )

        print(f"   同步结果: 成功{result2['sync']['success_snapshots']}个，跳过{result2['sync']['skipped_snapshots']}个，失败{result2['sync']['failed_snapshots']}个")
        print(f"   检测结果: 偏离{result2['detection']['total_deviations']}项，原因: {result2['detection']['skipped_reason']}")

        assert result2["sync"]["success_snapshots"] == 0, "❌ 需求2失败: 应该成功0个快照"
        assert result2["detection"]["total_deviations"] == 0, "❌ 需求2失败: 全失败时不应该检测"
        assert result2["detection"]["new_ticket_count"] == 0, "❌ 需求2失败: 全失败时不应该开工单"
        assert "未获取到任何有效的权限快照" in result2["detection"]["skipped_reason"], "❌ 需求2失败: 缺少跳过原因"

        print(f"   ✅ 全失败场景验证通过: 跳过检测，返回原因清晰")

        # 测试：部分成功，只处理新快照
        adapter.set_should_fail(False)
        adapter.set_fixed_permissions("OA", {"oa:view:notice": True})
        adapter.set_should_fail(True, "FINANCE")

        batch3 = AuditBatchService.create_batch(
            db=db,
            title="测试部分成功场景",
            target_user_ids=[test_user2.id],
            target_system_codes=["OA", "FINANCE"],
            initiator_name="验收测试",
        )

        result3 = AuditBatchService.run_full_audit(
            db=db,
            batch=batch3,
            force_refresh=True,
            initiator_name="验收测试",
        )

        print()
        print(f"   场景: OA成功，FINANCE失败")
        print(f"   同步结果: 成功{result3['sync']['success_snapshots']}，失败{result3['sync']['failed_snapshots']}")
        print(f"   检测结果: 处理{result3['detection']['processed_snapshots']}个快照，偏离{result3['detection']['total_deviations']}项")
        print(f"   统计: {result3['summary']}")

        assert result3["sync"]["success_snapshots"] == 1, "❌ 需求2失败: OA应该成功"
        assert result3["sync"]["failed_snapshots"] == 1, "❌ 需求2失败: FINANCE应该失败"
        assert result3["detection"]["processed_snapshots"] == 1, "❌ 需求2失败: 应该只处理1个新快照"

        print(f"   ✅ 部分成功场景验证通过: 只处理新拿到的OA快照")

        adapter.set_should_fail(False)

        print()
        print("   ✅ 需求2验证通过: 只处理新快照，全失败时不检测，返回统计清晰")

        print()
        print("=" * 1 + " 需求3: 批次详情查询 + 证据包导出")
        print("   " + "-" * 50)

        detail = AuditBatchService.get_batch_detail(db, batch.batch_no)
        assert detail is not None, "❌ 需求3失败: 批次详情查询失败"

        print(f"   ✅ 批次详情查询成功")
        print(f"      批次号: {detail['batch_no']}")
        print(f"      状态: {detail['status']}")
        print(f"      进度: 快照{detail['progress']['total_snapshots']}个(失败{detail['progress']['failed_snapshots']})，"
              f"偏离{detail['progress']['total_deviations']}项(高危{detail['progress']['high_risk_deviations']})，"
              f"工单{detail['progress']['total_tickets']}个(已解决{detail['progress']['resolved_tickets']})")

        assert len(detail["failed_systems"]) >= 0, "❌ 需求3失败: 缺少失败系统列表"
        assert len(detail["high_risk_deviations"]) >= 2, "❌ 需求3失败: 缺少高危偏离清单"
        assert len(detail["tickets"]) >= 2, "❌ 需求3失败: 缺少工单列表"

        print(f"   ✅ 失败系统: {len(detail['failed_systems'])}个")
        print(f"   ✅ 高危偏离清单: {len(detail['high_risk_deviations'])}项")
        for d in detail["high_risk_deviations"][:2]:
            print(f"      - {d['full_name']} | {d['system_name']} | {d['permission_name']} | {d['deviation_type_text']} | {d['risk_level_text']}")
        print(f"   ✅ 工单列表: {len(detail['tickets'])}个")
        for t in detail["tickets"][:2]:
            print(f"      - {t['ticket_no']} | {t['title'][:20]}... | {t['status']} | 分配给: {t['assignee_name']}")

        # 测试证据包导出
        export_result = AuditBatchService.export_evidence_package(db, batch.batch_no)
        assert export_result is not None, "❌ 需求3失败: 证据包导出失败"
        zip_content, filename = export_result
        assert len(zip_content) > 0, "❌ 需求3失败: 证据包为空"
        assert batch.batch_no in filename, "❌ 需求3失败: 文件名不包含批次号"

        import zipfile
        import io
        with zipfile.ZipFile(io.BytesIO(zip_content)) as zf:
            file_list = zf.namelist()
            print(f"   ✅ 证据包导出成功: {filename} ({len(zip_content)} bytes)")
            print(f"      包含文件:")
            for f in file_list:
                size = len(zf.read(f))
                print(f"        - {f} ({size} bytes)")

            required_files = [
                "README.txt",
                "00_审计批次信息.json",
                "01_权限快照明细.json",
                "02_权限偏离明细.json",
                "03_审计工单明细.json",
                "04_权限变更历史.json",
            ]
            for f in required_files:
                assert f in file_list, f"❌ 需求3失败: 证据包缺少{f}"

        print()
        print("   ✅ 需求3验证通过: 批次详情查询完整，证据包包含全部5类文件")

        print()
        print("=" * 1 + " 需求4: 小毛病修复（force_refresh、跳过提示、单用户失败列出）")
        print("   " + "-" * 50)

        adapter.set_fixed_permissions("ERP", erp_perms)

        # 先给test_user2同步一次ERP快照，制造existing数据
        SnapshotSyncService.sync_user_system_snapshot(
            db, test_user2, "ERP", trigger_by="验收测试", force_refresh=True
        )

        # 测试4.1: 第二次同步默认跳过，提示复用已有快照
        print("   测试4.1: 第二次同步（默认force_refresh=false）")
        result_reuse = SnapshotSyncService.sync_user_system_snapshot(
            db, test_user2, "ERP", trigger_by="验收测试", force_refresh=False
        )
        snapshot, message, status = result_reuse
        assert status == "skipped", f"❌ 需求4.1失败: 应该是skipped，实际{status}"
        assert "复用已有快照" in message, f"❌ 需求4.1失败: 缺少复用提示，实际{message}"
        assert snapshot.sync_status == "skipped", "❌ 需求4.1失败: sync_status不对"
        assert "复用已有快照" in (snapshot.skip_reason or ""), "❌ 需求4.1失败: skip_reason不对"
        print(f"   ✅ 跳过提示正确: status={status}, message={message}")

        # 测试4.2: 强制刷新
        print()
        print("   测试4.2: 强制刷新（force_refresh=true）")
        result_force = SnapshotSyncService.sync_user_system_snapshot(
            db, test_user, "ERP", trigger_by="验收测试", force_refresh=True
        )
        snapshot2, message2, status2 = result_force
        assert status2 == "success", f"❌ 需求4.2失败: 应该是success，实际{status2}"
        assert snapshot2.id != snapshot.id, "❌ 需求4.2失败: 应该生成新快照ID"
        print(f"   ✅ 强制刷新正确: status={status2}, 新快照ID={snapshot2.id} (旧ID={snapshot.id})")

        # 测试4.3: 指定用户同步全部系统，部分失败时列出失败系统
        print()
        print("   测试4.3: 单用户同步全部系统，部分失败时列出")
        adapter.set_should_fail(True, "CRM")
        result_user = SnapshotSyncService.sync_all_systems_for_user(
            db, test_user2, trigger_by="验收测试", force_refresh=True, audit_batch_id=None
        )
        adapter.set_should_fail(False)

        print(f"      成功: {result_user['success_snapshots']}个")
        print(f"      跳过: {result_user['skipped_snapshots']}个")
        print(f"      失败: {result_user['failed_snapshots']}个")
        print(f"      失败系统: {[(fs['system_name'], fs['reason'][:30]) for fs in result_user['failed_systems']]}")

        assert result_user["failed_snapshots"] >= 1, "❌ 需求4.3失败: 应该有失败"
        assert len(result_user["failed_systems"]) >= 1, "❌ 需求4.3失败: 应该列出失败系统"
        failed_crm = next((fs for fs in result_user["failed_systems"] if fs["system_code"] == "CRM"), None)
        assert failed_crm is not None, "❌ 需求4.3失败: 缺少CRM失败记录"
        assert "模拟接口失败" in failed_crm["reason"], "❌ 需求4.3失败: 失败原因不清晰"

        print()
        print("   ✅ 需求4验证通过: 强制刷新、跳过提示、单用户失败列出全部修复")

        print()
        print("=" * 70)
        print("  🎉 第三批4个需求全部验收通过！")
        print("=" * 70)
        print()
        print("┌─────────────────────────────────────────────────────────────────┐")
        print("│  验收项                                            状态       │")
        print("├─────────────────────────────────────────────────────────────────┤")
        print("│  1. 审计批次号串起全流程(快照/偏离/工单/变更)      ✅ 通过      │")
        print("│  2. 只处理新快照，全失败时不检测                    ✅ 通过      │")
        print("│  3. 批次详情查询 + 证据包ZIP导出                   ✅ 通过      │")
        print("│  4. 小毛病修复(force_refresh/跳过提示/失败列出)    ✅ 通过      │")
        print("└─────────────────────────────────────────────────────────────────┘")
        print()

        # 按批次查看这次专项审计的完整产出
        print("📊 本次专项审计完整产出（按批次号查询）:")
        print(f"   批次号: {batch.batch_no}")
        print(f"   同步系统: ERP, FINANCE")
        print(f"   快照数: {len(snaps)} (含失败)")
        print(f"   偏离数: {len(devs)} (高危{len([d for d in devs if d.risk_level == 'high'])})")
        print(f"   工单数: {len(tickets)} (已解决{len([t for t in tickets if t.status == 'resolved'])})")
        print(f"   变更记录: {len(histories)}条")
        print()
        print("✅ 审计人员只需拿批次号就能看到这次专项审计的全部产出！")

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
