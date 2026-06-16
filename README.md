# 权限合规审计系统

企业级权限合规审计平台，实现从权限快照同步、偏离检测、工单流转、专项审计到合规报告的全流程自动化管理。

## 功能特性

### 🔄 每日自动同步
- 定时从各业务系统同步用户权限快照
- 自动记录权限变更历史
- 支持手动触发同步

### 🎯 智能偏离检测
- 与岗位标准权限矩阵逐项比对
- 自动标记权限偏离（过高/过低）
- 基于系统重要性×偏离程度×权限类型计算风险分值
- 三档风险等级：高危 / 中危 / 低危

### 📋 审计工单管理
- **高风险偏离**自动生成审计工单
- 自动分配安全管理员处理
- **超48小时**未处理自动升级至安全总监
- 支持调整权限 / 更新风险 / 确认忽略三种处理方式
- 全流程操作留痕

### 🔍 专项审计
- 管理员可手动发起专项权限审计
- 支持按用户 / 系统范围定制审计
- 自动汇总关联系统权限变更历史

### 📊 合规报告
- **每天凌晨**自动生成权限合规报告
- 统计各系统权限偏离数、平均修复时长、审计完成率
- 支持导出 **PDF** 和 **Excel** 双格式

### ⚠️ 实时预警
- 高危偏离实时推送钉钉/企业微信安全群
- 工单升级即时通知安全总监
- 所有操作记录详细审计日志

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 运行测试（推荐）

```bash
python test_system.py
```

测试脚本会自动执行完整流程：
1. 初始化数据库
2. 加载示例数据（15用户/10岗位/完整权限矩阵）
3. 同步权限快照
4. 检测权限偏离
5. 生成审计工单
6. 发起专项审计
7. 生成合规报告(PDF+Excel)
8. 模拟工单处理

### 3. 启动服务

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

访问接口文档：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### 4. 配置环境变量（可选）

```bash
cp .env.example .env
# 编辑 .env 配置 Webhook 等参数
```

## 系统架构

```
app/
├── core/              # 核心配置
│   ├── config.py      # 系统配置
│   └── database.py    # 数据库连接
├── models/            # 数据模型（10张核心表）
├── schemas/           # Pydantic 数据结构
├── services/          # 业务服务层
│   ├── crud_service.py        # 基础CRUD
│   ├── snapshot_service.py    # 权限快照同步
│   ├── deviation_service.py   # 偏离检测与风险计算
│   ├── ticket_service.py      # 审计工单管理
│   ├── audit_service.py       # 专项审计与变更历史
│   ├── report_service.py      # 合规报告生成
│   └── scheduler_service.py   # 定时任务调度
├── routes/            # API路由层
└── utils/             # 工具模块
    ├── logger.py      # 日志
    ├── notification.py# 预警通知
    └── helpers.py     # 辅助函数

exports/               # 报告导出目录
logs/                  # 日志目录
```

## 核心数据表

| 表名 | 说明 |
|------|------|
| users | 系统用户 |
| positions | 岗位定义 |
| permission_matrix | 岗位标准权限矩阵 |
| permission_snapshots | 用户权限快照 |
| permission_deviations | 权限偏离记录 |
| audit_tickets | 审计工单 |
| permission_change_history | 权限变更历史 |
| audit_logs | 系统操作日志 |
| compliance_reports | 合规报告 |
| special_audits | 专项审计任务 |

## 默认定时任务

| 任务 | 执行时间 | 说明 |
|------|---------|------|
| 每日权限同步 | 02:00 | 同步快照 + 偏离检测 + 自动开工单 |
| 每日合规报告 | 03:00 | 生成日报 + PDF/Excel导出 |
| 工单升级检查 | 每小时整点 | 超48h未处理自动升级 |

## 默认账号

系统启动时会自动创建示例账号，在 `/docs` 中可通过用户列表接口查询。
