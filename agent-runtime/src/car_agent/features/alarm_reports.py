from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
AlarmStatus = Literal["OPEN", "ACKNOWLEDGED", "RESOLVED"]


class AlarmCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str | None = None
    category: str = Field(min_length=1, max_length=80)
    severity: Severity = "MEDIUM"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    location_id: str | None = Field(default=None, max_length=120)
    evidence_url: str | None = Field(default=None, max_length=1000)
    description: str | None = Field(default=None, max_length=1000)
    occurred_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AlarmAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator: str = Field(default="web-console", min_length=1, max_length=120)
    note: str = Field(default="", max_length=1000)


class ReportGenerate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str | None = None
    title: str | None = Field(default=None, max_length=200)
    include_resolved: bool = True
    use_llm: bool = True
    operator: str = Field(default="web-console", min_length=1, max_length=120)


class AlarmReportStore:
    def __init__(self, database_path: Path, reports_dir: Path) -> None:
        self.database_path = Path(database_path)
        self.reports_dir = Path(reports_dir)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _migrate(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS alarm_records (
                    id TEXT PRIMARY KEY,
                    task_id TEXT,
                    category TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    location_id TEXT,
                    evidence_url TEXT,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    acknowledged_at TEXT,
                    acknowledged_by TEXT,
                    resolved_at TEXT,
                    resolved_by TEXT,
                    resolution_note TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_alarm_records_status
                    ON alarm_records(status, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_alarm_records_task
                    ON alarm_records(task_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS generated_reports (
                    id TEXT PRIMARY KEY,
                    task_id TEXT,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    content_path TEXT NOT NULL,
                    alarm_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    generator TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_generated_reports_created
                    ON generated_reports(created_at DESC);
                """
            )

    def create_alarm(self, payload: AlarmCreate) -> dict[str, Any]:
        now = _utc_now()
        alarm_id = str(uuid4())
        occurred_at = _iso(payload.occurred_at) if payload.occurred_at else now
        description = payload.description or _default_alarm_description(
            payload.category,
            payload.severity,
            payload.location_id,
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO alarm_records (
                    id, task_id, category, severity, confidence, location_id,
                    evidence_url, description, status, occurred_at, created_at,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?)
                """,
                (
                    alarm_id,
                    payload.task_id,
                    payload.category,
                    payload.severity,
                    payload.confidence,
                    payload.location_id,
                    payload.evidence_url,
                    description,
                    occurred_at,
                    now,
                    json.dumps(payload.metadata, ensure_ascii=False),
                ),
            )
        alarm = self.get_alarm(alarm_id)
        assert alarm is not None
        return alarm

    def get_alarm(self, alarm_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM alarm_records WHERE id = ?",
                (alarm_id,),
            ).fetchone()
        return _alarm_row(row) if row else None

    def list_alarms(
        self,
        *,
        status: str | None = None,
        severity: str | None = None,
        task_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if status:
            clauses.append("status = ?")
            values.append(status)
        if severity:
            clauses.append("severity = ?")
            values.append(severity)
        if task_id:
            clauses.append("task_id = ?")
            values.append(task_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM alarm_records {where} "
                "ORDER BY occurred_at DESC LIMIT ?",
                values,
            ).fetchall()
        return [_alarm_row(row) for row in rows]

    def alarm_summary(self) -> dict[str, int]:
        result = {"total": 0, "open": 0, "acknowledged": 0, "resolved": 0}
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM alarm_records GROUP BY status"
            ).fetchall()
        for row in rows:
            count = int(row["count"])
            result["total"] += count
            key = str(row["status"]).lower()
            if key in result:
                result[key] = count
        return result

    def update_alarm(
        self,
        alarm_id: str,
        *,
        status: AlarmStatus,
        operator: str,
        note: str,
    ) -> dict[str, Any] | None:
        existing = self.get_alarm(alarm_id)
        if existing is None:
            return None
        now = _utc_now()
        with self._lock, self._connect() as connection:
            if status == "ACKNOWLEDGED":
                connection.execute(
                    """
                    UPDATE alarm_records
                    SET status = 'ACKNOWLEDGED', acknowledged_at = ?, acknowledged_by = ?
                    WHERE id = ? AND status = 'OPEN'
                    """,
                    (now, operator, alarm_id),
                )
            elif status == "RESOLVED":
                connection.execute(
                    """
                    UPDATE alarm_records
                    SET status = 'RESOLVED', resolved_at = ?, resolved_by = ?,
                        resolution_note = ?
                    WHERE id = ?
                    """,
                    (now, operator, note, alarm_id),
                )
        return self.get_alarm(alarm_id)

    def save_report(
        self,
        *,
        task_id: str | None,
        title: str,
        summary: str,
        content: str,
        alarm_count: int,
        created_by: str,
        generator: str,
    ) -> dict[str, Any]:
        report_id = str(uuid4())
        created_at = _utc_now()
        filename = f"{created_at[:10]}_{report_id}.md"
        path = self.reports_dir / filename
        path.write_text(content, encoding="utf-8")
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO generated_reports (
                    id, task_id, title, status, summary, content_path,
                    alarm_count, created_at, created_by, generator
                ) VALUES (?, ?, ?, 'READY', ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    task_id,
                    title,
                    summary,
                    str(path),
                    alarm_count,
                    created_at,
                    created_by,
                    generator,
                ),
            )
        report = self.get_report(report_id)
        assert report is not None
        return report

    def list_reports(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM generated_reports ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM generated_reports WHERE id = ?",
                (report_id,),
            ).fetchone()
        return dict(row) if row else None

    def report_content(self, report_id: str) -> str | None:
        report = self.get_report(report_id)
        if report is None:
            return None
        path = Path(report["content_path"])
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")


class ReportGenerator:
    def __init__(self, settings: Any) -> None:
        self.settings = settings

    async def generate(
        self,
        *,
        title: str,
        task: dict[str, Any] | None,
        alarms: list[dict[str, Any]],
        use_llm: bool,
    ) -> tuple[str, str]:
        local = _build_local_report(title=title, task=task, alarms=alarms)
        if not use_llm or not self._llm_available():
            return local, "local-template"
        try:
            enhanced = await self._enhance_with_llm(local)
            return enhanced, "openai-compatible"
        except Exception:
            return local, "local-template-fallback"

    def _llm_available(self) -> bool:
        return bool(
            getattr(self.settings, "llm_provider", "") == "openai_compatible"
            and getattr(self.settings, "llm_api_key", "")
            and getattr(self.settings, "llm_base_url", "")
            and getattr(self.settings, "llm_model", "")
        )

    async def _enhance_with_llm(self, draft: str) -> str:
        base_url = str(self.settings.llm_base_url).rstrip("/")
        endpoint = f"{base_url}/chat/completions"
        timeout = float(getattr(self.settings, "llm_timeout_sec", 20))
        payload = {
            "model": self.settings.llm_model,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是智慧园区巡检报告编辑器。保持事实不变，禁止补充未提供的坐标、"
                        "告警或处置结果。输出结构清晰、适合归档的中文 Markdown。"
                    ),
                },
                {"role": "user", "content": draft},
            ],
        }
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM returned empty report")
        return content.strip() + "\n"


def register_alarm_report_routes(
    app: FastAPI,
    settings: Any,
    authorize: Any,
    events: Any,
    database: Any,
) -> None:
    database_path = Path(settings.database_path)
    reports_dir = Path(getattr(settings, "reports_dir", database_path.parent / "reports"))
    store = AlarmReportStore(database_path, reports_dir)
    generator = ReportGenerator(settings)
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(authorize)])

    app.state.alarm_report_store = store

    @router.get("/alarms")
    async def list_alarms(
        status: str | None = Query(default=None),
        severity: str | None = Query(default=None),
        task_id: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        return {
            "items": store.list_alarms(
                status=status,
                severity=severity,
                task_id=task_id,
                limit=limit,
            )
        }

    @router.get("/alarms/summary")
    async def alarm_summary() -> dict[str, int]:
        return store.alarm_summary()

    @router.post("/alarms", status_code=201)
    async def create_alarm(body: AlarmCreate) -> dict[str, Any]:
        alarm = store.create_alarm(body)
        await events.broadcast(
            "ALARM_CREATED",
            alarm,
            task_id=alarm.get("task_id"),
        )
        return alarm

    @router.post("/alarms/{alarm_id}/acknowledge")
    async def acknowledge_alarm(alarm_id: str, body: AlarmAction) -> dict[str, Any]:
        alarm = store.update_alarm(
            alarm_id,
            status="ACKNOWLEDGED",
            operator=body.operator,
            note=body.note,
        )
        if alarm is None:
            raise HTTPException(status_code=404, detail="alarm not found")
        await events.broadcast("ALARM_UPDATED", alarm, task_id=alarm.get("task_id"))
        return alarm

    @router.post("/alarms/{alarm_id}/resolve")
    async def resolve_alarm(alarm_id: str, body: AlarmAction) -> dict[str, Any]:
        alarm = store.update_alarm(
            alarm_id,
            status="RESOLVED",
            operator=body.operator,
            note=body.note,
        )
        if alarm is None:
            raise HTTPException(status_code=404, detail="alarm not found")
        await events.broadcast("ALARM_UPDATED", alarm, task_id=alarm.get("task_id"))
        return alarm

    @router.get("/reports")
    async def list_reports(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        return {"items": store.list_reports(limit=limit)}

    @router.post("/reports/generate", status_code=201)
    async def generate_report(body: ReportGenerate) -> dict[str, Any]:
        task = database.get_task(body.task_id) if body.task_id else database.get_current_task()
        if body.task_id and task is None:
            raise HTTPException(status_code=404, detail="task not found")
        task_id = body.task_id or (task or {}).get("id") or (task or {}).get("task_id")
        statuses = None if body.include_resolved else "OPEN"
        alarms = store.list_alarms(status=statuses, task_id=task_id, limit=500)
        title = body.title or _default_report_title(task, task_id)
        content, source = await generator.generate(
            title=title,
            task=task,
            alarms=alarms,
            use_llm=body.use_llm,
        )
        summary = _report_summary(task, alarms)
        report = store.save_report(
            task_id=task_id,
            title=title,
            summary=summary,
            content=content,
            alarm_count=len(alarms),
            created_by=body.operator,
            generator=source,
        )
        await events.broadcast("REPORT_CREATED", report, task_id=task_id)
        return report

    @router.get("/reports/{report_id}")
    async def get_report(report_id: str) -> dict[str, Any]:
        report = store.get_report(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="report not found")
        return report

    @router.get("/reports/{report_id}/content", response_class=PlainTextResponse)
    async def report_content(report_id: str) -> str:
        content = store.report_content(report_id)
        if content is None:
            raise HTTPException(status_code=404, detail="report content not found")
        return content

    app.include_router(router)


def _alarm_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    try:
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
    except json.JSONDecodeError:
        item["metadata"] = {}
    return item


def _default_alarm_description(category: str, severity: str, location_id: str | None) -> str:
    labels = {
        "flooding": "检测到路面积水",
        "pothole": "检测到路面坑洼",
        "obstacle": "检测到道路障碍物",
        "person": "检测到人员进入巡检区域",
        "fire": "检测到疑似烟火异常",
    }
    subject = labels.get(category.lower(), f"检测到 {category}")
    location = f"，位置：{location_id}" if location_id else ""
    return f"{subject}{location}，告警等级：{severity}。"


def _default_report_title(task: dict[str, Any] | None, task_id: str | None) -> str:
    name = _task_name(task)
    if name != "未命名任务":
        return f"{name}巡检报告"
    if task_id:
        return f"巡检任务 {task_id[:8]} 报告"
    return "智慧园区综合巡检报告"



def _task_name(task: dict[str, Any] | None) -> str:
    if not task:
        return "未命名任务"
    direct = task.get("name")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    plan = task.get("plan")
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except json.JSONDecodeError:
            plan = None
    if isinstance(plan, dict):
        name = plan.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return "未命名任务"

def _report_summary(task: dict[str, Any] | None, alarms: list[dict[str, Any]]) -> str:
    state = (task or {}).get("state", "未关联任务")
    open_count = sum(item["status"] == "OPEN" for item in alarms)
    return f"任务状态 {state}，共记录 {len(alarms)} 个告警，其中 {open_count} 个待处理。"


def _build_local_report(
    *,
    title: str,
    task: dict[str, Any] | None,
    alarms: list[dict[str, Any]],
) -> str:
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    task_id = (task or {}).get("id") or (task or {}).get("task_id") or "未关联"
    task_state = (task or {}).get("state") or "未知"
    task_name = _task_name(task)
    counts: dict[str, int] = {}
    for alarm in alarms:
        counts[alarm["severity"]] = counts.get(alarm["severity"], 0) + 1

    lines = [
        f"# {title}",
        "",
        f"**生成时间：** {generated_at}",
        "",
        "## 1. 任务概览",
        "",
        f"- 任务名称：{task_name}",
        f"- 任务 ID：{task_id}",
        f"- 最终状态：{task_state}",
        f"- 告警总数：{len(alarms)}",
        "",
        "## 2. 告警统计",
        "",
    ]
    if counts:
        for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
            if severity in counts:
                lines.append(f"- {severity}：{counts[severity]}")
    else:
        lines.append("- 本次巡检未记录告警。")

    lines.extend(["", "## 3. 告警明细", ""])
    if not alarms:
        lines.append("无。")
    for index, alarm in enumerate(alarms, start=1):
        lines.extend(
            [
                f"### 3.{index} {alarm['description']}",
                "",
                f"- 类别：{alarm['category']}",
                f"- 等级：{alarm['severity']}",
                f"- 状态：{alarm['status']}",
                f"- 置信度：{float(alarm['confidence']) * 100:.1f}%",
                f"- 位置：{alarm.get('location_id') or '未知'}",
                f"- 发生时间：{alarm['occurred_at']}",
                f"- 证据：{alarm.get('evidence_url') or '无'}",
                "",
            ]
        )

    lines.extend(
        [
            "## 4. 结论与后续处理",
            "",
            _report_summary(task, alarms),
            "",
            "本报告由车端系统基于任务记录与结构化告警自动生成。",
            "",
        ]
    )
    return "\n".join(lines)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
