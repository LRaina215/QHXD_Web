import json
import sqlite3
from datetime import datetime
from pathlib import Path

from app.schemas import AlertEvent, CommandLogEntry, MissionActionResult, RobotState, TaskStatus


class SqlitePersistence:
    """Local-development friendly SQLite persistence for Phase 1."""

    def __init__(self) -> None:
        self._db_path = Path(__file__).resolve().parents[2] / "data" / "rk3588_phase1.db"

    @property
    def db_path(self) -> Path:
        return self._db_path

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS command_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command TEXT NOT NULL,
                    source TEXT NOT NULL,
                    requested_by TEXT,
                    payload_json TEXT NOT NULL,
                    accepted INTEGER NOT NULL,
                    detail TEXT NOT NULL,
                    task_status_json TEXT NOT NULL,
                    received_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id TEXT PRIMARY KEY,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    source TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    acknowledged INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS state_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    updated_at TEXT NOT NULL,
                    task_state TEXT NOT NULL,
                    battery_percent INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def save_command_log(
        self,
        command: str,
        source: str,
        requested_by: str | None,
        payload: dict[str, str | int | float | bool | None],
        result: MissionActionResult,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO command_logs (
                    command, source, requested_by, payload_json, accepted,
                    detail, task_status_json, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command,
                    source,
                    requested_by,
                    json.dumps(payload, ensure_ascii=False),
                    1 if result.accepted else 0,
                    result.detail,
                    json.dumps(result.task_status.model_dump(mode="json"), ensure_ascii=False),
                    result.received_at.isoformat(),
                ),
            )
            connection.execute(
                """
                DELETE FROM command_logs
                WHERE id NOT IN (
                    SELECT id FROM command_logs ORDER BY id DESC LIMIT 200
                )
                """
            )
            connection.commit()

    def list_command_logs(self, limit: int = 20) -> list[CommandLogEntry]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, command, source, requested_by, payload_json, accepted,
                       detail, task_status_json, received_at
                FROM command_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            CommandLogEntry(
                id=row["id"],
                command=row["command"],
                source=row["source"],
                requested_by=row["requested_by"],
                payload=json.loads(row["payload_json"]),
                accepted=bool(row["accepted"]),
                detail=row["detail"],
                task_status=TaskStatus.model_validate(json.loads(row["task_status_json"])),
                received_at=datetime.fromisoformat(row["received_at"]),
            )
            for row in rows
        ]

    def save_alert(self, alert: AlertEvent) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO alerts (
                    alert_id, level, message, source, timestamp, acknowledged
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    alert.alert_id,
                    alert.level,
                    alert.message,
                    alert.source,
                    alert.timestamp.isoformat(),
                    1 if alert.acknowledged else 0,
                ),
            )
            connection.execute(
                """
                DELETE FROM alerts
                WHERE alert_id NOT IN (
                    SELECT alert_id FROM alerts ORDER BY timestamp DESC LIMIT 50
                )
                """
            )
            connection.commit()

    def list_recent_alerts(self, limit: int = 10) -> list[AlertEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT alert_id, level, message, source, timestamp, acknowledged
                FROM alerts
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            AlertEvent(
                alert_id=row["alert_id"],
                level=row["level"],
                message=row["message"],
                source=row["source"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                acknowledged=bool(row["acknowledged"]),
            )
            for row in rows
        ]

    def save_state_snapshot(self, state: RobotState) -> None:
        payload = state.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO state_snapshots (updated_at, task_state, battery_percent, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    state.updated_at.isoformat(),
                    state.task_status.state,
                    state.device_status.battery_percent,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            connection.execute(
                """
                DELETE FROM state_snapshots
                WHERE id NOT IN (
                    SELECT id FROM state_snapshots ORDER BY id DESC LIMIT 500
                )
                """
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection


persistence = SqlitePersistence()
