import sys
sys.path.insert(0, '.')
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from fastapi.testclient import TestClient
from main import create_app

from app.core.database import Base, engine, SessionLocal
from app.services import CRUDService
from app.models import *

print("=" * 60)
print("  权限合规审计系统 - API 功能测试")
print("=" * 60)

print("\n[初始化] 创建数据库表结构...")
Base.metadata.create_all(bind=engine)

db = SessionLocal()
try:
    print("[初始化] 加载示例数据...")
    CRUDService.init_sample_data(db)
    user_count = db.query(User).count()
    pos_count = db.query(Position).count()
    matrix_count = db.query(PermissionMatrix).count()
    print(f"  ✓ 用户: {user_count}, 岗位: {pos_count}, 权限矩阵: {matrix_count}")
finally:
    db.close()

app = create_app()
client = TestClient(app)

# Test 1: List users
print("\n[1/8] 用户列表接口...")
r = client.get('/api/v1/system/users?page_size=5')
assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
data = r.json()
print(f"  ✓ 用户数: {data['total']}")

# Test 2: List positions
print("\n[2/8] 岗位列表接口...")
r = client.get('/api/v1/system/positions?page_size=5')
assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
data = r.json()
print(f"  ✓ 岗位数: {data['total']}")

# Test 3: Dashboard
print("\n[3/8] 仪表盘总览...")
r = client.get('/api/v1/reports/dashboard/overview')
assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
d = r.json()['data']
print(f"  ✓ 用户: {d['users_count']} 人")
print(f"  ✓ 快照: {d['snapshots_count']} 个")
print(f"  ✓ 偏离: {d['deviations']['total']} 项")
print(f"  ✓ 工单: {d['tickets']['total']} 个")

# Test 4: Trigger sync
print("\n[4/8] 权限快照同步...")
r = client.post('/api/v1/sync/snapshot', json={})
assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
d = r.json().get('data', {})
print(f"  ✓ 同步用户: {d.get('success_users', 0)} / {d.get('total_users', 0)}")
print(f"  ✓ 生成快照: {d.get('total_snapshots', 0)} 个")

# Test 5: Run detection
print("\n[5/8] 权限偏离检测...")
r = client.post('/api/v1/sync/detect')
assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
d = r.json().get('data', {})
print(f"  ✓ 处理快照: {d.get('processed_snapshots', 0)} 个")
print(f"  ✓ 检测偏离: {d.get('total_deviations', 0)} 项")
print(f"  ✓ 高危偏离: {d.get('high_risk_count', 0)} 项")

# Test 6: Auto generate tickets
print("\n[6/8] 自动生成审计工单...")
r = client.post('/api/v1/tickets/auto-generate')
assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
count = r.json().get('count', 0)
print(f"  ✓ 生成工单: {count} 个")

# Test 7: Generate report
print("\n[7/8] 生成合规报告...")
r = client.post('/api/v1/reports/daily/generate')
assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
d = r.json().get('data', {})
print(f"  ✓ 报告日期: {d.get('report_date')}")
print(f"  ✓ 偏离总数: {d.get('total_deviations')}")
print(f"  ✓ 完成率: {d.get('audit_completion_rate')}%")
pdf_ok = "✓" if d.get('pdf_path') else "○"
excel_ok = "✓" if d.get('excel_path') else "○"
print(f"  {pdf_ok} PDF报告: {d.get('pdf_path')}")
print(f"  {excel_ok} Excel报告: {d.get('excel_path')}")

# Test 8: Special audit
print("\n[8/8] 发起专项审计...")
audit_data = {
    "title": "API测试-全系统权限审计",
    "audit_type": "manual",
    "target_user_ids": None,
    "target_system_codes": ["ERP", "FINANCE"],
}
r = client.post('/api/v1/audit/special', json=audit_data)
assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
print(f"  ✓ 审计状态: {r.json().get('data', {}).get('status')}")
print(f"  ✓ 摘要: {str(r.json().get('data', {}).get('summary', ''))[:60]}...")

print("\n" + "=" * 60)
print("  ✅ 全部 8 项 API 测试通过！")
print("=" * 60)
print(f"\n📊 最终数据库统计:")
r = client.get('/api/v1/reports/dashboard/overview')
d = r.json()['data']
print(f"   - 用户: {d['users_count']} 人")
print(f"   - 快照: {d['snapshots_count']} 个")
print(f"   - 偏离总数: {d['deviations']['total']} 项")
dev_stats = d['deviations']
by_risk = dev_stats.get('by_risk', {})
print(f"   - 风险分布: 高危{by_risk.get('high', 0)} / 中危{by_risk.get('medium', 0)} / 低危{by_risk.get('low', 0)}")
print(f"   - 工单: {d['tickets']['total']} 个")
print(f"   - 待处理高危: {d['pending_high_risk']} 项")
print(f"\n🚀 启动服务: 运行 uvicorn main:app --reload")
print(f"📖 访问文档: http://localhost:8000/docs")
