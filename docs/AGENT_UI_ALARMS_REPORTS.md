# 自然语言控制页、告警中心与巡检报告

## 功能范围

本补丁在现有 `devcp` LangGraph 项目上增加：

- 全屏自然语言巡检任务中心。
- 结构化计划展示与人工确认。
- 当前任务状态、暂停、继续和取消。
- Agent WebSocket 事件时间线。
- 告警列表、等级/状态筛选、确认与解决。
- 基于任务和告警记录生成 Markdown 巡检报告。
- 报告列表、预览和下载。
- OpenAI-compatible LLM 可选润色；不可用时自动使用本地模板。

## 新增 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/alarms` | 查询告警 |
| GET | `/api/v1/alarms/summary` | 告警统计 |
| POST | `/api/v1/alarms` | 写入结构化告警 |
| POST | `/api/v1/alarms/{id}/acknowledge` | 确认告警 |
| POST | `/api/v1/alarms/{id}/resolve` | 解决告警 |
| GET | `/api/v1/reports` | 报告列表 |
| POST | `/api/v1/reports/generate` | 生成报告 |
| GET | `/api/v1/reports/{id}` | 报告元数据 |
| GET | `/api/v1/reports/{id}/content` | Markdown 内容 |

所有接口继续使用现有 Agent Bearer Token。控制台通过 Node.js 反向代理访问，不向浏览器暴露 Token。

## YOLO 告警接入示例

```http
POST /api/v1/alarms
Authorization: Bearer <AGENT_TOKEN>
Content-Type: application/json

{
  "task_id": "当前任务ID",
  "category": "flooding",
  "severity": "HIGH",
  "confidence": 0.92,
  "location_id": "east_gate",
  "evidence_url": "/evidence/20260713_001.jpg",
  "description": "东门检测到路面积水"
}
```

## 数据持久化

- 告警写入 Agent 现有 SQLite 数据库中的 `alarm_records` 表。
- 报告元数据写入 `generated_reports` 表。
- Markdown 文件保存在数据库同级目录的 `reports/` 下。
- SQLite 使用 WAL，允许控制台读取与后台事件写入并发执行。

## 安全约束

自然语言页不包含任何速度控制入口。进入该页面时，控制台会停止当前手动控制；任务运动仍必须经过结构化计划、本地校验和人工确认。
