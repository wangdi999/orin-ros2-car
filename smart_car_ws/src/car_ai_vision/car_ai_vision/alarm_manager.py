"""
报警消抖状态机模块。

每个 danger_type 独立维护状态机，实现：
  IDLE → DETECTED(发布报警) → COOLDOWN(抑制重复报警) → RECOVERY → IDLE

冷却时间：
  - person_detected: 30 秒
  - abnormal_behavior: 10 秒
"""

import time
from enum import Enum, auto


class AlarmState(Enum):
    """报警状态机状态枚举。"""
    IDLE = auto()       # 空闲，可触发新报警
    DETECTED = auto()   # 检测到目标，发布报警后立即进入 COOLDOWN
    COOLDOWN = auto()   # 冷却中，抑制重复报警
    RECOVERY = auto()   # 恢复期，目标消失后等待确认


# 各类别冷却时间（秒）
COOLDOWN_CONFIG = {
    "person_detected": 30,
    "abnormal_behavior": 10,
    "cracked_tile": 30,
}


class AlarmDebouncer:
    """
    按 danger_type 独立维护的报警消抖状态机。

    每个 danger_type 拥有独立的状态和冷却计时器，
    不同类别之间互不影响。
    """

    def __init__(self):
        """初始化所有 danger_type 的状态机。"""
        self._states = {}
        self._cooldown_until = {}
        self._recovery_until = {}
        self._recovery_duration = 2.0  # 恢复期观察时长（秒）

        for danger_type in COOLDOWN_CONFIG:
            self._states[danger_type] = AlarmState.IDLE
            self._cooldown_until[danger_type] = 0.0
            self._recovery_until[danger_type] = 0.0

    def should_publish(self, danger_type: str) -> bool:
        """
        检查指定 danger_type 当前是否允许发布报警。

        调用此方法会驱动状态机转换：
        - IDLE 状态且冷却已过 → 允许发布 → 进入 COOLDOWN
        - COOLDOWN 状态冷却未过 → 拒绝发布

        Args:
            danger_type: 危险类别枚举值

        Returns:
            True 表示允许发布报警，False 表示应抑制
        """
        if danger_type not in self._states:
            self._states[danger_type] = AlarmState.IDLE
            self._cooldown_until[danger_type] = 0.0
            self._recovery_until[danger_type] = 0.0

        now = time.time()
        state = self._states[danger_type]

        if state == AlarmState.IDLE:
            # 检查是否还在冷却期
            if now < self._cooldown_until[danger_type]:
                return False
            # IDLE → DETECTED：允许发布
            self._states[danger_type] = AlarmState.DETECTED
            return True

        elif state == AlarmState.DETECTED:
            # 上一周期已发布，进入 COOLDOWN
            cooldown = COOLDOWN_CONFIG.get(danger_type, 30)
            self._cooldown_until[danger_type] = now + cooldown
            self._states[danger_type] = AlarmState.COOLDOWN
            return False

        elif state == AlarmState.COOLDOWN:
            if now >= self._cooldown_until[danger_type]:
                # 冷却期满，进入 RECOVERY 观察
                self._states[danger_type] = AlarmState.RECOVERY
                self._recovery_until[danger_type] = (
                    now + self._recovery_duration
                )
            return False

        elif state == AlarmState.RECOVERY:
            if now >= self._recovery_until[danger_type]:
                # 恢复期结束，回到 IDLE
                self._states[danger_type] = AlarmState.IDLE
            return False

        return False

    def reset(self, danger_type: str) -> None:
        """
        手动重置指定 danger_type 的状态机到 IDLE。

        Args:
            danger_type: 危险类别枚举值
        """
        self._states[danger_type] = AlarmState.IDLE
        self._cooldown_until[danger_type] = 0.0
        self._recovery_until[danger_type] = 0.0

    def get_state(self, danger_type: str) -> AlarmState:
        """
        获取指定 danger_type 的当前状态。

        Args:
            danger_type: 危险类别枚举值

        Returns:
            当前 AlarmState 枚举值
        """
        return self._states.get(danger_type, AlarmState.IDLE)

    def get_cooldown_remaining(self, danger_type: str) -> float:
        """
        获取指定 danger_type 剩余冷却时间（秒）。

        Args:
            danger_type: 危险类别枚举值

        Returns:
            剩余冷却秒数，若不在冷却期则返回 0.0
        """
        now = time.time()
        remaining = self._cooldown_until.get(danger_type, 0.0) - now
        return max(0.0, remaining)
