from pathlib import Path

from car_agent.models.plan import PatrolPlan
from car_agent.repositories.database import Database


def test_task_creation_is_persisted(tmp_path: Path) -> None:
    db = Database(tmp_path / "agent.db")
    plan = PatrolPlan(name="巡检", waypoints=["home"])
    created = db.create_task(
        task_id="task-1",
        thread_id="thread-1",
        plan=plan,
        created_by="tester",
    )
    assert created["task_id"] == "task-1"
    assert created["state"] == "AWAITING_APPROVAL"
    assert created["waypoints"][0]["location_id"] == "home"

    updated = db.update_task_state("task-1", "READY")
    assert updated is not None
    assert updated["state"] == "READY"
    assert updated["approved_at"] is not None
    db.close()
