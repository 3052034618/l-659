import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

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

def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        CRUDService.init_sample_data(db)
        AdapterFactory.set_adapter_type("mock")
        adapter = get_business_system_adapter()
        adapter.set_should_fail(False)
        adapter.set_adjust_should_fail(False)

        # 清理
        for model in [PermissionChangeHistory, AuditTicket, PermissionDeviation, PermissionSnapshot, SpecialAudit]:
            db.query(model).delete()
        db.commit()

        test_user = db.query(User).filter(User.username == "fin_zhang").first()

        # 设置ERP权限
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

        print("=== 创建批次 ===")
        batch = AuditBatchService.create_batch(
            db=db,
            title="测试",
            target_user_ids=[test_user.id],
            target_system_codes=["ERP", "FINANCE"],
            initiator_name="测试",
        )
        print(f"批次ID: {batch.id}, batch_no: {batch.batch_no}")

        print("\n=== 执行批次 ===")
        result = AuditBatchService.run_full_audit(
            db=db,
            batch=batch,
            force_refresh=True,
            initiator_name="测试",
        )
        print(f"结果: {result}")

        print("\n=== 查询数据库确认数据 ===")
        batch_id = batch.id
        snaps = db.query(PermissionSnapshot).filter(PermissionSnapshot.audit_batch_id == batch_id).all()
        print(f"快照(关联batch_id={batch_id}): {len(snaps)}个")
        for s in snaps:
            print(f"  - id={s.id}, system={s.system_code}, status={s.sync_status}")

        devs = db.query(PermissionDeviation).filter(PermissionDeviation.audit_batch_id == batch_id).all()
        print(f"\n偏离(关联batch_id={batch_id}): {len(devs)}个")
        for d in devs:
            print(f"  - id={d.id}, perm={d.permission_code}, risk={d.risk_level}")

        tickets = db.query(AuditTicket).filter(AuditTicket.audit_batch_id == batch_id).all()
        print(f"\n工单(关联batch_id={batch_id}): {len(tickets)}个")
        for t in tickets:
            print(f"  - id={t.id}, status={t.status}")

    finally:
        db.close()
        AdapterFactory.set_adapter_type("real")

if __name__ == "__main__":
    main()
