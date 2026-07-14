from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class NamedLocation:
    location_id: str
    display_name: str
    x: float
    y: float
    yaw: float
    enabled: bool


class LocationStore:
    def __init__(self, path: str):
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        self._items = {
            item["location_id"]: NamedLocation(
                location_id=item["location_id"],
                display_name=item["display_name"],
                x=float(item["x"]),
                y=float(item["y"]),
                yaw=float(item["yaw"]),
                enabled=bool(item.get("enabled", True)),
            )
            for item in raw.get("locations", [])
        }

    def get(self, location_id: str) -> NamedLocation | None:
        return self._items.get(location_id)

    def resolve_enabled(self, location_ids: list[str]) -> tuple[list[NamedLocation], list[str]]:
        resolved: list[NamedLocation] = []
        errors: list[str] = []
        for location_id in location_ids:
            item = self.get(location_id)
            if item is None:
                errors.append(f"UNKNOWN_LOCATION:{location_id}")
            elif not item.enabled:
                errors.append(f"LOCATION_DISABLED:{location_id}")
            else:
                resolved.append(item)
        return resolved, errors
