import json
import sqlite3
from datetime import datetime
from pathlib import Path

from app.schemas import AlertEvent, CommandLogEntry, MissionActionResult, RobotState, TaskEvent, TaskStatus, VisualEventRecord


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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_events (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    task_state TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    source TEXT NOT NULL,
                    waypoint_id TEXT,
                    remaining_distance REAL,
                    progress INTEGER NOT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_events_task_time ON task_events(task_id, timestamp DESC)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS visual_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    level TEXT NOT NULL,
                    class_name TEXT,
                    message TEXT NOT NULL,
                    source TEXT NOT NULL,
                    task_id TEXT,
                    waypoint_id TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    duration_s REAL NOT NULL,
                    max_confidence REAL,
                    count INTEGER NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_visual_events_recent ON visual_events(last_seen_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_visual_events_type_class ON visual_events(event_type, class_name, last_seen_at DESC)"
            )
            connection.commit()

    def upsert_visual_event(
        self,
        *,
        event_type: str,
        level: str,
        class_name: str | None,
        message: str,
        source: str,
        task_id: str | None,
        waypoint_id: str | None,
        timestamp: datetime,
        max_confidence: float | None,
        time_window_seconds: float = 8.0,
    ) -> VisualEventRecord:
        window = max(1.0, time_window_seconds)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM visual_events
                WHERE event_type = ?
                  AND COALESCE(class_name, '') = COALESCE(?, '')
                ORDER BY last_seen_at DESC
                LIMIT 1
                """,
                (event_type, class_name),
            ).fetchone()

            if row is not None:
                last_seen_at = datetime.fromisoformat(row["last_seen_at"])
                age_s = (timestamp - last_seen_at).total_seconds()
                if 0 <= age_s <= window:
                    first_seen_at = datetime.fromisoformat(row["first_seen_at"])
                    duration_s = max(0.0, (timestamp - first_seen_at).total_seconds())
                    merged_confidence = self._max_optional_float(row["max_confidence"], max_confidence)
                    connection.execute(
                        """
                        UPDATE visual_events
                        SET level = ?, message = ?, source = ?, task_id = ?, waypoint_id = ?,
                            last_seen_at = ?, duration_s = ?, max_confidence = ?,
                            count = count + 1, status = ?
                        WHERE event_id = ?
                        """,
                        (
                            level,
                            message,
                            source,
                            task_id,
                            waypoint_id,
                            timestamp.isoformat(),
                            duration_s,
                            merged_confidence,
                            "active",
                            row["event_id"],
                        ),
                    )
                    connection.commit()
                    return self.get_visual_event(str(row["event_id"]))  # type: ignore[return-value]

            safe_class = class_name or "none"
            event_id = f"{event_type}:{safe_class}:{int(timestamp.timestamp())}"
            connection.execute(
                """
                INSERT INTO visual_events (
                    event_id, event_type, level, class_name, message, source,
                    task_id, waypoint_id, first_seen_at, last_seen_at, duration_s,
                    max_confidence, count, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event_type,
                    level,
                    class_name,
                    message,
                    source,
                    task_id,
                    waypoint_id,
                    timestamp.isoformat(),
                    timestamp.isoformat(),
                    0.0,
                    max_confidence,
                    1,
                    "active",
                ),
            )
            connection.execute(
                """
                DELETE FROM visual_events
                WHERE event_id NOT IN (
                    SELECT event_id FROM visual_events ORDER BY last_seen_at DESC LIMIT 500
                )
                """
            )
            connection.commit()
            return self.get_visual_event(event_id)  # type: ignore[return-value]

    def get_visual_event(self, event_id: str) -> VisualEventRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM visual_events WHERE event_id = ?", (event_id,)).fetchone()
        return self._visual_event_from_row(row) if row is not None else None

    def list_visual_events(
        self,
        limit: int = 50,
        event_type: str | None = None,
        task_id: str | None = None,
    ) -> list[VisualEventRecord]:
        limit = max(1, min(limit, 200))
        clauses: list[str] = []
        params: list[object] = []
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if task_id:
            clauses.append("task_id = ?")
            params.append(task_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM visual_events {where} ORDER BY last_seen_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [self._visual_event_from_row(row) for row in rows]

    def save_task_event(self, event: TaskEvent) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO task_events (
                    event_id, task_id, event_type, task_state, detail, source,
                    waypoint_id, remaining_distance, progress, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.task_id,
                    event.event_type,
                    event.task_state,
                    event.detail,
                    event.source,
                    event.waypoint_id,
                    event.remaining_distance,
                    event.progress,
                    event.timestamp.isoformat(),
                ),
            )
            connection.execute(
                """
                DELETE FROM task_events
                WHERE event_id NOT IN (
                    SELECT event_id FROM task_events ORDER BY timestamp DESC LIMIT 1000
                )
                """
            )
            connection.commit()
            return cursor.rowcount > 0

    def list_task_events(self, limit: int = 50, task_id: str | None = None) -> list[TaskEvent]:
        limit = max(1, min(limit, 200))
        with self._connect() as connection:
            if task_id:
                rows = connection.execute(
                    """
                    SELECT * FROM task_events WHERE task_id = ?
                    ORDER BY timestamp DESC LIMIT ?
                    """,
                    (task_id, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM task_events ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [
            TaskEvent(
                event_id=row["event_id"],
                task_id=row["task_id"],
                event_type=row["event_type"],
                task_state=row["task_state"],
                detail=row["detail"],
                source=row["source"],
                waypoint_id=row["waypoint_id"],
                remaining_distance=row["remaining_distance"],
                progress=row["progress"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
            )
            for row in rows
        ]

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

    @staticmethod
    def _max_optional_float(left: float | None, right: float | None) -> float | None:
        values = [value for value in (left, right) if value is not None]
        return max(values) if values else None

    @staticmethod
    def _visual_event_from_row(row: sqlite3.Row) -> VisualEventRecord:
        return VisualEventRecord(
            event_id=row["event_id"],
            event_type=row["event_type"],
            level=row["level"],
            class_name=row["class_name"],
            message=row["message"],
            source=row["source"],
            task_id=row["task_id"],
            waypoint_id=row["waypoint_id"],
            first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
            duration_s=float(row["duration_s"]),
            max_confidence=row["max_confidence"],
            count=int(row["count"]),
            status=row["status"],
        )


persistence = SqlitePersistence()
