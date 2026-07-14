from pathlib import Path

from car_agent.features.alarm_reports import AlarmCreate, AlarmReportStore


def test_alarm_lifecycle_and_report_storage(tmp_path: Path) -> None:
    store = AlarmReportStore(tmp_path / "agent.db", tmp_path / "reports")
    alarm = store.create_alarm(
        AlarmCreate(
            task_id="task-1",
            category="flooding",
            severity="HIGH",
            confidence=0.92,
            location_id="east_gate",
        )
    )
    assert alarm["status"] == "OPEN"
    assert store.alarm_summary()["open"] == 1

    acknowledged = store.update_alarm(
        alarm["id"],
        status="ACKNOWLEDGED",
        operator="tester",
        note="",
    )
    assert acknowledged is not None
    assert acknowledged["status"] == "ACKNOWLEDGED"

    resolved = store.update_alarm(
        alarm["id"],
        status="RESOLVED",
        operator="tester",
        note="现场已清理",
    )
    assert resolved is not None
    assert resolved["status"] == "RESOLVED"
    assert store.alarm_summary()["resolved"] == 1

    report = store.save_report(
        task_id="task-1",
        title="测试巡检报告",
        summary="测试摘要",
        content="# 测试巡检报告\n",
        alarm_count=1,
        created_by="tester",
        generator="local-template",
    )
    assert store.get_report(report["id"])["alarm_count"] == 1
    assert store.report_content(report["id"]) == "# 测试巡检报告\n"


def test_alarm_and_report_routes(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from car_agent.features.alarm_reports import register_alarm_report_routes

    class Events:
        async def broadcast(self, *_args, **_kwargs) -> None:
            return None

    class Database:
        def get_task(self, task_id: str):
            return {"task_id": task_id, "state": "SUCCEEDED", "name": "测试任务"}

        def get_current_task(self):
            return None

    async def authorize() -> None:
        return None

    settings = SimpleNamespace(
        database_path=tmp_path / "agent.db",
        llm_provider="mock",
        llm_api_key="",
        llm_base_url="",
        llm_model="",
        llm_timeout_sec=5,
    )
    app = FastAPI()
    register_alarm_report_routes(app, settings, authorize, Events(), Database())

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/alarms",
            json={
                "task_id": "task-1",
                "category": "obstacle",
                "severity": "MEDIUM",
                "confidence": 0.88,
            },
        )
        assert created.status_code == 201
        alarm_id = created.json()["id"]
        assert client.get("/api/v1/alarms/summary").json()["open"] == 1

        acknowledged = client.post(
            f"/api/v1/alarms/{alarm_id}/acknowledge",
            json={"operator": "tester", "note": "已查看"},
        )
        assert acknowledged.status_code == 200
        assert acknowledged.json()["status"] == "ACKNOWLEDGED"

        report = client.post(
            "/api/v1/reports/generate",
            json={"task_id": "task-1", "use_llm": False, "operator": "tester"},
        )
        assert report.status_code == 201
        report_id = report.json()["id"]
        content = client.get(f"/api/v1/reports/{report_id}/content")
        assert content.status_code == 200
        assert "测试任务" in content.text
