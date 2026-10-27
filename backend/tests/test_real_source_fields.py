import json
import sqlite3
from datetime import datetime, timezone

from app.schemas import DeviceStatus, EnvSensor, PlatformStatus, SystemMode
from app.services.mock_state import MockStateService
from app.services.persistence import SqlitePersistence
from app.services.state_store import StateStore


def test_unmeasured_schema_defaults_are_null():
    assert DeviceStatus().battery_percent is None
    assert EnvSensor().temperature_c is None and EnvSensor().humidity_percent is None


def test_switch_to_real_removes_mock_sensor_values():
    store = StateStore()
    store.initialize(MockStateService().get_latest_state())
    assert store.get_latest_state().device_status.battery_percent is not None
    state = store.switch_mode(SystemMode(mode="real", updated_at=datetime.now(timezone.utc)))
    assert state.device_status.battery_percent is None
    assert state.env_sensor.temperature_c is None and state.env_sensor.humidity_percent is None
    assert state.env_sensor.status == "offline"


def test_real_uart_profile_cannot_retain_old_mock_measurements():
    old = MockStateService().get_latest_state()
    store = StateStore()
    store.initialize(old.model_copy(update={"system_mode": SystemMode(mode="real", updated_at=datetime.now(timezone.utc))}))
    state = store.update_platform_status(PlatformStatus(source="fpga_bridge", nav_link="online",
        nav_link_kind="uart:/dev/ttyACM0", updated_at=datetime.now(timezone.utc)))
    assert state.device_status.battery_percent is None and state.env_sensor.temperature_c is None


def test_unknown_battery_survives_legacy_sqlite_storage_as_JSON_null(tmp_path):
    db = SqlitePersistence()
    db._db_path = tmp_path / "state.db"
    db.initialize()
    state = MockStateService().get_latest_state()
    state.device_status.battery_percent = None
    db.save_state_snapshot(state)
    with sqlite3.connect(db.db_path) as c:
        indexed, payload = c.execute("SELECT battery_percent,payload_json FROM state_snapshots").fetchone()
    assert indexed == -1
    assert json.loads(payload)["device_status"]["battery_percent"] is None


def test_offline_status_without_a_link_kind_is_accepted():
    store = StateStore()
    state = MockStateService().get_latest_state()
    store.initialize(state.model_copy(update={"system_mode": SystemMode(mode="real", updated_at=datetime.now(timezone.utc))}))
    updated = store.update_platform_status(PlatformStatus(source="fpga_bridge", nav_link="offline",
                                                        updated_at=datetime.now(timezone.utc)))
    assert updated.platform_status.nav_link == "offline"
