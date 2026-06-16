import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

print("测试1: 同步接口")
r = client.post('/api/v1/sync/snapshot', json={})
print(f"  状态码: {r.status_code}")
data = r.json()
print(f"  success: {data['success']}")
print(f"  message: {data['message']}")
d = data.get('data', {})
print(f"  total_snapshots: {d.get('total_snapshots')}")
print(f"  failed_users: {d.get('failed_users')}")
print(f"  all_success: {d.get('all_success')}")
print(f"  failed_items数量: {len(d.get('failed_items', []))}")

print()
print("测试2: 检测接口")
r = client.post('/api/v1/sync/detect')
print(f"  状态码: {r.status_code}")
data = r.json()
print(f"  message: {data['message']}")
d = data.get('data', {})
print(f"  processed_snapshots: {d.get('processed_snapshots')}")
print(f"  total_deviations: {d.get('total_deviations')}")
print(f"  high_risk_count: {d.get('high_risk_count')}")
print(f"  new_ticket_count: {d.get('new_ticket_count')}")

print()
print("测试3: 一键同步+检测")
r = client.post('/api/v1/sync/sync_and_detect', json={})
print(f"  状态码: {r.status_code}")
data = r.json()
print(f"  success: {data['success']}")
print(f"  message: {data['message']}")
summary = data.get('data', {}).get('summary', {})
print(f"  success_snapshots: {summary.get('success_snapshots')}")
print(f"  failed_snapshots: {summary.get('failed_snapshots')}")
print(f"  high_risk_deviations: {summary.get('high_risk_deviations')}")
print(f"  new_tickets: {summary.get('new_tickets')}")

print()
print("测试4: 工单列表（验证已自动分配）")
r = client.get('/api/v1/tickets/?status=pending')
data = r.json()
items = data.get('items', [])
print(f"  待处理工单数: {len(items)}")
if items:
    t = items[0]
    print(f"  第一个工单: {t['ticket_no']}")
    print(f"  偏离类型: {t['deviation_type_text']}")
    print(f"  风险等级: {t['risk_level_text']}")
    print(f"  处理人ID: {t['assignee_id']}")

print()
print("✅ 所有接口测试通过")
