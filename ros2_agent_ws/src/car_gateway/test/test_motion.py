from car_gateway.motion import normalize_motion_payload


def test_normalize_forward_distance_motion() -> None:
    command = normalize_motion_payload(
        {
            "action": "MOVE",
            "direction": "FORWARD",
            "distance_m": 0.10,
            "max_speed_mps": 0.05,
        }
    )

    assert command.action == "MOVE"
    assert command.linear_x == 0.05
    assert command.linear_y == 0.0
    assert command.duration_sec == 2.0


def test_normalize_rejects_fast_motion() -> None:
    try:
        normalize_motion_payload(
            {
                "action": "MOVE",
                "direction": "FORWARD",
                "distance_m": 0.10,
                "max_speed_mps": 0.20,
            }
        )
    except ValueError as exc:
        assert "speed exceeds" in str(exc)
    else:
        raise AssertionError("expected validation error")


def test_stop_command_has_zero_duration() -> None:
    command = normalize_motion_payload({"action": "STOP"})

    assert command.action == "STOP"
    assert command.duration_sec == 0.0
