from __future__ import annotations

import math
import subprocess


def clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def sanitize_velocity(
    linear_x: float,
    linear_y: float,
    angular_z: float,
    *,
    max_linear_x: float,
    max_linear_y: float,
    max_angular_z: float,
    deadband_linear: float,
) -> tuple[float, float, float] | None:
    if not all(math.isfinite(item) for item in (linear_x, linear_y, angular_z)):
        return None
    safe_x = clamp(linear_x, abs(max_linear_x))
    safe_y = clamp(linear_y, abs(max_linear_y))
    safe_z = clamp(angular_z, abs(max_angular_z))
    if abs(safe_x) < deadband_linear:
        safe_x = 0.0
    if abs(safe_y) < deadband_linear:
        safe_y = 0.0
    if abs(safe_z) < 1e-6:
        safe_z = 0.0
    return safe_x, safe_y, safe_z


def encode_motion_packet(*, car_type: int, linear_x: float, linear_y: float) -> bytes:
    """Encode Rosmaster App cmd 0x10.

    The App parses num_x/num_y as signed int8, then maps:
      speed_x = num_y / 100.0
      speed_y = -num_x / 100.0
    """

    num_y = _to_signed_percent(linear_x)
    num_x = _to_signed_percent(-linear_y)
    payload = [
        car_type & 0xFF,
        0x10,
        0x06,
        _to_uint8(num_x),
        _to_uint8(num_y),
    ]
    checksum = sum(payload) % 256
    return ("$" + "".join(f"{item:02x}" for item in payload + [checksum]) + "#").encode(
        "utf-8"
    )


def _to_signed_percent(value: float) -> int:
    return int(round(clamp(value, 1.0) * 100.0))


def _to_uint8(value: int) -> int:
    return value % 256


def resolve_app_host(value: str, *, port: int = 6000) -> str:
    if value.strip().lower() != "auto":
        return value
    try:
        result = subprocess.run(
            ["ss", "-lnt"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return "127.0.0.1"
    suffix = f":{port}"
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 4 or not fields[3].endswith(suffix):
            continue
        host = fields[3].rsplit(":", 1)[0].strip("[]")
        if host and host != "0.0.0.0":
            return host
    return "127.0.0.1"
