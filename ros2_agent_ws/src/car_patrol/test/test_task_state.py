import pytest

from car_patrol.task_state import PatrolState, PatrolTask


def test_happy_path() -> None:
    task = PatrolTask(task_id="1", name="test", location_ids=["a", "b"])
    task.start()
    task.waypoint_succeeded()
    assert task.state == PatrolState.RUNNING
    assert task.current_index == 1
    task.waypoint_succeeded()
    assert task.state == PatrolState.SUCCEEDED


def test_retry_exhaustion_requires_recovery() -> None:
    task = PatrolTask(task_id="1", name="test", location_ids=["a"], max_retries=1)
    task.start()
    assert task.waypoint_failed("NAV", "failed") is True
    assert task.waypoint_failed("NAV", "failed") is False
    assert task.state == PatrolState.RECOVERY_REQUIRED


def test_invalid_transition_is_rejected() -> None:
    task = PatrolTask(task_id="1", name="test", location_ids=["a"])
    with pytest.raises(ValueError):
        task.pause()
