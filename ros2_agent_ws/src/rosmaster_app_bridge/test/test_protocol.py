import math

from rosmaster_app_bridge.protocol import encode_motion_packet, resolve_app_host, sanitize_velocity


def test_encode_motion_packet_zero() -> None:
    assert encode_motion_packet(car_type=1, linear_x=0.0, linear_y=0.0) == b"$011006000017#"


def test_encode_motion_packet_maps_app_axes() -> None:
    assert encode_motion_packet(car_type=1, linear_x=0.08, linear_y=0.02) == b"$011006fe081d#"


def test_sanitize_velocity_clamps_and_deadbands() -> None:
    assert sanitize_velocity(
        0.2,
        -0.001,
        0.5,
        max_linear_x=0.08,
        max_linear_y=0.08,
        max_angular_z=0.0,
        deadband_linear=0.005,
    ) == (0.08, 0.0, 0.0)


def test_sanitize_velocity_rejects_non_finite() -> None:
    assert (
        sanitize_velocity(
            math.nan,
            0.0,
            0.0,
            max_linear_x=0.08,
            max_linear_y=0.08,
            max_angular_z=0.0,
            deadband_linear=0.005,
        )
        is None
    )


def test_resolve_app_host_returns_explicit_value() -> None:
    assert resolve_app_host("192.0.2.10") == "192.0.2.10"
