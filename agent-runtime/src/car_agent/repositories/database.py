from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from car_agent.models.plan import Location, PatrolPlan


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS locations (
    location_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    yaw REAL NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    description TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    name TEXT NOT NULL,
    state TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    current_index INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    approved_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    last_error_code TEXT,
    last_error_message TEXT
);

CREATE TABLE IF NOT EXISTS task_waypoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    location_id TEXT NOT NULL,
    state TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    finished_at TEXT,
    error_message TEXT,
    UNIQUE(task_id, sequence_no),
    FOREIGN KEY(task_id) REFERENCES tasks(task_id)
);

CREATE TABLE IF NOT EXISTS alarms (
    alarm_id TEXT PRIMARY KEY,
    task_id TEXT,
    danger_type TEXT NOT NULL,
    confidence REAL NOT NULL,
    frame_id TEXT,
    pos_x REAL,
    pos_y REAL,
    location_id TEXT,
    bbox_json TEXT,
    image_path TEXT,
    local_action TEXT NOT NULL,
    handling_state TEXT NOT NULL,
    generated_message TEXT,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    task_id TEXT,
    thread_id TEXT,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    severity TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operator TEXT NOT NULL,
    action TEXT NOT NULL,
    target_id TEXT,
    request_json TEXT,
    result TEXT NOT NULL,
    error_code TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT,
    purpose TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    latency_ms INTEGER,
    error_type TEXT,
    created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def sync_locations_from_yaml(self, path: Path | str) -> int:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        items = [Location.model_validate(item) for item in raw.get("locations", [])]
        now = utc_now()
        with self.transaction() as conn:
            for item in items:
                conn.execute(
                    """
                    INSERT INTO locations (
                        location_id, display_name, x, y, yaw, enabled,
                        description, priority, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(location_id) DO UPDATE SET
                        display_name=excluded.display_name,
                        x=excluded.x,
                        y=excluded.y,
                        yaw=excluded.yaw,
                        enabled=excluded.enabled,
                        description=excluded.description,
                        priority=excluded.priority,
                        updated_at=excluded.updated_at
                    """,
                    (
                        item.location_id,
                        item.display_name,
                        item.x,
                        item.y,
                        item.yaw,
                        int(item.enabled),
                        item.description,
                        item.priority,
                        now,
                    ),
                )
        return len(items)

    def list_locations(self, *, enabled_only: bool = False) -> list[Location]:
        sql = "SELECT * FROM locations"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY priority DESC, location_id ASC"
        rows = self._conn.execute(sql).fetchall()
        return [
            Location(
                location_id=row["location_id"],
                display_name=row["display_name"],
                x=row["x"],
                y=row["y"],
                yaw=row["yaw"],
                enabled=bool(row["enabled"]),
                description=row["description"] or "",
                priority=row["priority"],
            )
            for row in rows
        ]

    def create_task(
        self,
        *,
        task_id: str,
        thread_id: str,
        plan: PatrolPlan,
        created_by: str,
        state: str = "AWAITING_APPROVAL",
    ) -> dict[str, Any]:
        created_at = utc_now()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id, thread_id, name, state, plan_json,
                    created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    thread_id,
                    plan.name,
                    state,
                    plan.model_dump_json(),
                    created_by,
                    created_at,
                ),
            )
            for index, location_id in enumerate(plan.waypoints):
                conn.execute(
                    """
                    INSERT INTO task_waypoints (task_id, sequence_no, location_id, state)
                    VALUES (?, ?, ?, 'PENDING')
                    """,
                    (task_id, index, location_id),
                )
        return self.get_task(task_id) or {}

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["plan"] = json.loads(item.pop("plan_json"))
        item["waypoints"] = [
            dict(waypoint)
            for waypoint in self._conn.execute(
                "SELECT * FROM task_waypoints WHERE task_id = ? ORDER BY sequence_no",
                (task_id,),
            ).fetchall()
        ]
        return item

    def get_task_by_thread(self, thread_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT task_id FROM tasks WHERE thread_id = ? ORDER BY created_at DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
        return None if row is None else self.get_task(row["task_id"])

    def get_current_task(self) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT task_id FROM tasks
            WHERE state IN ('AWAITING_APPROVAL', 'READY', 'RUNNING', 'PAUSED', 'RECOVERY_REQUIRED')
            ORDER BY created_at DESC LIMIT 1
            """
        ).fetchone()
        return None if row is None else self.get_task(row["task_id"])

    def update_task_state(
        self,
        task_id: str,
        state: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any] | None:
        now = utc_now()
        approved_at = now if state == "READY" else None
        started_at = now if state == "RUNNING" else None
        finished_at = now if state in {"SUCCEEDED", "FAILED", "CANCELLED"} else None
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE tasks SET
                    state = ?,
                    approved_at = COALESCE(?, approved_at),
                    started_at = COALESCE(?, started_at),
                    finished_at = COALESCE(?, finished_at),
                    last_error_code = ?,
                    last_error_message = ?
                WHERE task_id = ?
                """,
                (
                    state,
                    approved_at,
                    started_at,
                    finished_at,
                    error_code,
                    error_message,
                    task_id,
                ),
            )
        return self.get_task(task_id)

    def add_audit(
        self,
        *,
        operator: str,
        action: str,
        target_id: str | None,
        request: dict[str, Any],
        result: str,
        error_code: str | None = None,
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO audit_logs (
                    operator, action, target_id, request_json, result, error_code, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operator,
                    action,
                    target_id,
                    json.dumps(request, ensure_ascii=False, separators=(",", ":")),
                    result,
                    error_code,
                    utc_now(),
                ),
            )
