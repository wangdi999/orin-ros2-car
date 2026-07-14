from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PatrolState(str, Enum):
    IDLE = "IDLE"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


TERMINAL_STATES = {
    PatrolState.SUCCEEDED,
    PatrolState.FAILED,
    PatrolState.CANCELLED,
}


@dataclass
class PatrolTask:
    task_id: str
    name: str
    location_ids: list[str]
    event_policy: dict = field(default_factory=dict)
    return_home: bool = False
    current_index: int = 0
    retry_count: int = 0
    max_retries: int = 1
    state: PatrolState = PatrolState.READY
    last_error_code: str = ""
    last_error_message: str = ""

    @property
    def current_location_id(self) -> str:
        if 0 <= self.current_index < len(self.location_ids):
            return self.location_ids[self.current_index]
        return ""

    @property
    def complete(self) -> bool:
        return self.current_index >= len(self.location_ids)

    def start(self) -> None:
        self._require(PatrolState.READY)
        self.state = PatrolState.RUNNING

    def pause(self) -> None:
        self._require(PatrolState.RUNNING)
        self.state = PatrolState.PAUSED

    def resume(self) -> None:
        self._require(PatrolState.PAUSED)
        self.state = PatrolState.RUNNING

    def cancel(self) -> None:
        if self.state not in {
            PatrolState.READY,
            PatrolState.RUNNING,
            PatrolState.PAUSED,
            PatrolState.RECOVERY_REQUIRED,
        }:
            raise ValueError(f"cannot cancel from {self.state}")
        self.state = PatrolState.CANCELLED

    def waypoint_succeeded(self) -> None:
        self._require(PatrolState.RUNNING)
        self.current_index += 1
        self.retry_count = 0
        if self.complete:
            self.state = PatrolState.SUCCEEDED

    def waypoint_failed(self, code: str, message: str) -> bool:
        self._require(PatrolState.RUNNING)
        self.retry_count += 1
        self.last_error_code = code
        self.last_error_message = message
        if self.retry_count > self.max_retries:
            self.state = PatrolState.RECOVERY_REQUIRED
            return False
        return True

    def retry_current(self) -> None:
        self._require(PatrolState.RECOVERY_REQUIRED)
        self.retry_count = 0
        self.state = PatrolState.RUNNING

    def skip_current(self) -> None:
        self._require(PatrolState.RECOVERY_REQUIRED)
        self.current_index += 1
        self.retry_count = 0
        self.state = PatrolState.SUCCEEDED if self.complete else PatrolState.RUNNING

    def _require(self, expected: PatrolState) -> None:
        if self.state != expected:
            raise ValueError(f"expected {expected}, got {self.state}")
