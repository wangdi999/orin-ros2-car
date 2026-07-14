"""地点存储模块单元测试。"""

from pathlib import Path

import pytest
import yaml

from car_patrol.location_store import LocationStore, NamedLocation


@pytest.fixture
def locations_file(tmp_path: Path) -> Path:
    data = {
        "locations": [
            {
                "location_id": "home",
                "display_name": "起点",
                "x": 0.0,
                "y": 0.0,
                "yaw": 0.0,
                "enabled": True,
            },
            {
                "location_id": "east_gate",
                "display_name": "东门",
                "x": 1.0,
                "y": 0.0,
                "yaw": 1.57,
                "enabled": False,
            },
        ]
    }
    path = tmp_path / "locations.yaml"
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_get_returns_named_location(locations_file: Path) -> None:
    store = LocationStore(str(locations_file))
    home = store.get("home")
    assert home == NamedLocation(
        location_id="home",
        display_name="起点",
        x=0.0,
        y=0.0,
        yaw=0.0,
        enabled=True,
    )


def test_get_unknown_returns_none(locations_file: Path) -> None:
    store = LocationStore(str(locations_file))
    assert store.get("missing") is None


def test_resolve_enabled_filters_disabled_and_unknown(
    locations_file: Path,
) -> None:
    store = LocationStore(str(locations_file))
    resolved, errors = store.resolve_enabled(["home", "east_gate", "missing"])
    assert len(resolved) == 1
    assert resolved[0].location_id == "home"
    assert "LOCATION_DISABLED:east_gate" in errors
    assert "UNKNOWN_LOCATION:missing" in errors


def test_builtin_config_loads(locations_file: Path) -> None:
    builtin = (
        Path(__file__).resolve().parents[1] / "config" / "locations.yaml"
    )
    store = LocationStore(str(builtin))
    assert store.get("home") is not None
    assert store.get("home").enabled is True
