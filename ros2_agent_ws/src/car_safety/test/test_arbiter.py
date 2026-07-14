from car_safety.arbiter import Limits, Velocity, choose_velocity, sanitize


def test_emergency_stop_has_highest_priority() -> None:
    source, velocity = choose_velocity(
        emergency_stopped=True,
        now_ms=1000,
        teleop=Velocity(0.1, 0.0, 0.0),
        teleop_at_ms=999,
        teleop_timeout_ms=450,
        navigation=Velocity(0.1, 0.0, 0.0),
        navigation_at_ms=999,
        navigation_timeout_ms=500,
        patrol_running=True,
    )
    assert source == "EMERGENCY_STOP"
    assert velocity == Velocity()


def test_manual_has_priority_over_navigation() -> None:
    source, velocity = choose_velocity(
        emergency_stopped=False,
        now_ms=1000,
        teleop=Velocity(0.05, 0.0, 0.0),
        teleop_at_ms=999,
        teleop_timeout_ms=450,
        navigation=Velocity(0.1, 0.0, 0.0),
        navigation_at_ms=999,
        navigation_timeout_ms=500,
        patrol_running=True,
    )
    assert source == "MANUAL_TELEOP"
    assert velocity.linear_x == 0.05


def test_sanitize_clamps_and_rejects_nan() -> None:
    limits = Limits(0.1, 0.1, 0.3)
    assert sanitize(Velocity(1.0, -1.0, 2.0), limits) == Velocity(0.1, -0.1, 0.3)
    assert sanitize(Velocity(float("nan"), 0.0, 0.0), limits) is None
