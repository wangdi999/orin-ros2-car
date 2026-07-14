"""
car_safety/arbiter.py 扩展单元测试。

在现有 3 个测试基础上补充：
  - 超时检测（手柄超时 → 降级到导航/零速度）
  - 导航仅在巡逻运行时有效
  - 导航超时 → 零速度
  - 边界限幅（负向速度、零速度、对称限幅）
  - 多源竞争完整场景
"""

from car_safety.arbiter import Limits, Velocity, choose_velocity, sanitize


# ============================================================
# choose_velocity 扩展测试
# ============================================================

def test_teleop_timeout_falls_back_to_navigation() -> None:
    """手柄超时后应在巡逻运行时降级到导航。"""
    source, velocity = choose_velocity(
        emergency_stopped=False,
        now_ms=1000,
        teleop=Velocity(0.05, 0.0, 0.0),
        teleop_at_ms=500,  # 500ms 前，超时（timeout=450）
        teleop_timeout_ms=450,
        navigation=Velocity(0.08, 0.0, 0.0),
        navigation_at_ms=999,  # 1ms 前，新鲜
        navigation_timeout_ms=500,
        patrol_running=True,
    )
    assert source == "NAVIGATION"
    assert velocity.linear_x == 0.08


def test_teleop_timeout_falls_back_to_zero_when_no_patrol() -> None:
    """手柄超时且巡逻未运行 → 零速度。"""
    source, velocity = choose_velocity(
        emergency_stopped=False,
        now_ms=1000,
        teleop=Velocity(0.05, 0.0, 0.0),
        teleop_at_ms=500,
        teleop_timeout_ms=450,
        navigation=Velocity(0.08, 0.0, 0.0),
        navigation_at_ms=999,
        navigation_timeout_ms=500,
        patrol_running=False,  # 巡逻未运行
    )
    assert source == "ZERO"
    assert velocity == Velocity()


def test_navigation_only_valid_when_patrol_running() -> None:
    """导航速度仅在 patrol_running=True 时被采纳。"""
    source, velocity = choose_velocity(
        emergency_stopped=False,
        now_ms=1000,
        teleop=Velocity(),
        teleop_at_ms=None,  # 无手柄输入
        teleop_timeout_ms=450,
        navigation=Velocity(0.08, 0.0, 0.0),
        navigation_at_ms=999,
        navigation_timeout_ms=500,
        patrol_running=False,  # 注意：巡逻未运行
    )
    assert source == "ZERO"
    assert velocity == Velocity()


def test_navigation_timeout_falls_back_to_zero() -> None:
    """导航超时 → 零速度。"""
    source, velocity = choose_velocity(
        emergency_stopped=False,
        now_ms=1000,
        teleop=Velocity(),
        teleop_at_ms=None,
        teleop_timeout_ms=450,
        navigation=Velocity(0.08, 0.0, 0.0),
        navigation_at_ms=400,  # 600ms 前，超时（timeout=500）
        navigation_timeout_ms=500,
        patrol_running=True,
    )
    assert source == "ZERO"
    assert velocity == Velocity()


def test_no_inputs_yields_zero() -> None:
    """无任何输入 → 零速度。"""
    source, velocity = choose_velocity(
        emergency_stopped=False,
        now_ms=1000,
        teleop=Velocity(),
        teleop_at_ms=None,
        teleop_timeout_ms=450,
        navigation=Velocity(),
        navigation_at_ms=None,
        navigation_timeout_ms=500,
        patrol_running=True,
    )
    assert source == "ZERO"
    assert velocity == Velocity()


def test_teleop_at_boundary_not_timeout() -> None:
    """手柄刚好在超时边界（now - at == timeout）不算超时。"""
    source, velocity = choose_velocity(
        emergency_stopped=False,
        now_ms=1000,
        teleop=Velocity(0.05, 0.0, 0.0),
        teleop_at_ms=550,  # 1000-550=450, timeout=450 → 不在超时
        teleop_timeout_ms=450,
        navigation=Velocity(0.08, 0.0, 0.0),
        navigation_at_ms=999,
        navigation_timeout_ms=500,
        patrol_running=True,
    )
    assert source == "MANUAL_TELEOP"


def test_navigation_at_boundary_not_timeout() -> None:
    """导航刚好在超时边界不算超时。"""
    source, velocity = choose_velocity(
        emergency_stopped=False,
        now_ms=1000,
        teleop=Velocity(),
        teleop_at_ms=None,
        teleop_timeout_ms=450,
        navigation=Velocity(0.08, 0.0, 0.0),
        navigation_at_ms=500,  # 1000-500=500, timeout=500 → 不在超时
        navigation_timeout_ms=500,
        patrol_running=True,
    )
    assert source == "NAVIGATION"


# ============================================================
# sanitize 扩展测试
# ============================================================

def test_sanitize_negative_velocity() -> None:
    """负向速度应被限幅到负上限。"""
    limits = Limits(0.10, 0.15, 0.30)
    result = sanitize(Velocity(-0.50, -0.50, -1.0), limits)
    assert result is not None
    assert result.linear_x == -0.10
    assert result.linear_y == -0.15
    assert result.angular_z == -0.30


def test_sanitize_zero_velocity() -> None:
    """零速度不变。"""
    limits = Limits(0.10, 0.10, 0.30)
    result = sanitize(Velocity(0.0, 0.0, 0.0), limits)
    assert result == Velocity(0.0, 0.0, 0.0)


def test_sanitize_within_limits_unchanged() -> None:
    """限幅范围内的速度不变。"""
    limits = Limits(0.10, 0.10, 0.30)
    result = sanitize(Velocity(0.05, -0.03, 0.20), limits)
    assert result.linear_x == 0.05
    assert result.linear_y == -0.03
    assert result.angular_z == 0.20


def test_sanitize_rejects_inf() -> None:
    """Inf 速度应返回 None。"""
    limits = Limits(0.10, 0.10, 0.30)
    assert sanitize(Velocity(float("inf"), 0.0, 0.0), limits) is None
    assert sanitize(Velocity(0.0, float("-inf"), 0.0), limits) is None
    assert sanitize(Velocity(0.0, 0.0, float("inf")), limits) is None


def test_sanitize_rejects_all_nan() -> None:
    """所有分量为 NaN 时返回 None。"""
    limits = Limits(0.10, 0.10, 0.30)
    assert sanitize(Velocity(float("nan"), float("nan"), float("nan")), limits) is None


def test_sanitize_asymmetric_limits() -> None:
    """非对称限幅边界测试。"""
    limits = Limits(0.10, 0.05, 0.30)  # linear_y 限制更小
    result = sanitize(Velocity(0.08, 0.08, 0.50), limits)
    assert result.linear_x == 0.08  # 未超限
    assert result.linear_y == 0.05  # 被限幅
    assert result.angular_z == 0.30  # 被限幅


def test_choose_velocity_teleop_absent_navigation_fresh() -> None:
    """无手柄、巡逻运行、导航新鲜 → NAVIGATION。"""
    source, velocity = choose_velocity(
        emergency_stopped=False,
        now_ms=2000,
        teleop=Velocity(),
        teleop_at_ms=None,
        teleop_timeout_ms=450,
        navigation=Velocity(0.06, 0.0, 0.1),
        navigation_at_ms=1950,
        navigation_timeout_ms=500,
        patrol_running=True,
    )
    assert source == "NAVIGATION"
    assert velocity.linear_x == 0.06
    assert velocity.angular_z == 0.1
