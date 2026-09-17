"""SQLite persistence for incident history, outages, and SLA tracking."""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("sentinel.storage")


@dataclass
class IncidentRecord:
    """Structured record of an outage incident."""

    id: int
    target_name: str
    target_url: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    duration_seconds: float | None = None
    error_reason: str | None = None
    severity: str = "critical"
    status: str = "ongoing"

    def to_dict(self) -> dict[str, Any]:
        """Convert record to dictionary."""
        return {
            "id": self.id,
            "target_name": self.target_name,
            "target_url": self.target_url,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "duration_seconds": self.duration_seconds,
            "error_reason": self.error_reason,
            "severity": self.severity,
            "status": self.status,
        }


class IncidentStore:
    """Thread-safe SQLite persistent store for target outages and incident lifecycles."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is not None:
            self.db_path = Path(db_path) if str(db_path) != ":memory:" else db_path
        else:
            env_path = os.environ.get("SENTINEL_DB_PATH")
            if env_path:
                self.db_path = Path(env_path)
            else:
                sentinel_home = Path.home() / ".sentinel"
                self.db_path = sentinel_home / "history.db"

        if isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create or reuse connection with WAL journal mode enabled."""
        if self._conn is None:
            db_target = str(self.db_path) if isinstance(self.db_path, Path) else self.db_path
            self._conn = sqlite3.connect(
                db_target,
                timeout=10.0,
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            if db_target != ":memory:":
                try:
                    self._conn.execute("PRAGMA journal_mode=WAL;")
                    self._conn.execute("PRAGMA synchronous=NORMAL;")
                except Exception as exc:
                    logger.debug("Could not set WAL pragma: %s", exc)
        return self._conn

    def _init_db(self) -> None:
        """Initialize required database tables and indices."""
        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_name TEXT NOT NULL,
                    target_url TEXT,
                    started_at TEXT NOT NULL,
                    resolved_at TEXT,
                    duration_seconds REAL,
                    error_reason TEXT,
                    severity TEXT DEFAULT 'critical',
                    status TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_incidents_started
                ON incidents(started_at DESC);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_incidents_status
                ON incidents(status);
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_name TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    latency_ms REAL NOT NULL,
                    checked_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_samples_target_time
                ON samples(target_name, checked_at DESC);
                """
            )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> IncidentRecord:
        """Convert an SQLite row to a typed IncidentRecord instance."""
        started_at = (
            datetime.fromisoformat(row["started_at"])
            if row["started_at"]
            else datetime.now(UTC)
        )
        resolved_at = (
            datetime.fromisoformat(row["resolved_at"])
            if row["resolved_at"]
            else None
        )
        return IncidentRecord(
            id=row["id"],
            target_name=row["target_name"],
            target_url=row["target_url"],
            started_at=started_at,
            resolved_at=resolved_at,
            duration_seconds=row["duration_seconds"],
            error_reason=row["error_reason"],
            severity=row["severity"] or "critical",
            status=row["status"] or "ongoing",
        )

    def record_outage_start(
        self,
        target_name: str,
        target_url: str = "",
        error_reason: str = "",
        severity: str = "critical",
        started_at: datetime | None = None,
    ) -> int:
        """Record the initiation of a service outage idempotently."""
        conn = self._get_connection()
        with conn:
            cursor = conn.execute(
                "SELECT id FROM incidents WHERE target_name = ? AND status = 'ongoing' ORDER BY id DESC LIMIT 1;",
                (target_name,),
            )
            existing = cursor.fetchone()
            if existing:
                return int(existing["id"])

            ts = (started_at or datetime.now(UTC)).isoformat()
            cursor = conn.execute(
                """
                INSERT INTO incidents (
                    target_name, target_url, started_at, error_reason, severity, status
                ) VALUES (?, ?, ?, ?, ?, 'ongoing');
                """,
                (target_name, target_url, ts, error_reason, severity),
            )
            incident_id = cursor.lastrowid or 0
        logger.info("Recorded outage incident #%d for '%s'", incident_id, target_name)
        return incident_id

    def record_recovery(
        self,
        target_name: str,
        incident_id: int | None = None,
        recovered_at: datetime | None = None,
        duration_seconds: float | None = None,
    ) -> IncidentRecord | None:
        """Record recovery from an outage, resolving ongoing incident records."""
        rec_dt = recovered_at or datetime.now(UTC)
        ts = rec_dt.isoformat()
        conn = self._get_connection()
        with conn:
            if incident_id is not None:
                cursor = conn.execute(
                    "SELECT * FROM incidents WHERE id = ?;", (incident_id,)
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM incidents WHERE target_name = ? AND status = 'ongoing' ORDER BY id DESC LIMIT 1;",
                    (target_name,),
                )
            row = cursor.fetchone()
            if not row:
                return None

            inc_id = row["id"]
            start_dt = (
                datetime.fromisoformat(row["started_at"])
                if row["started_at"]
                else rec_dt
            )
            dur = (
                duration_seconds
                if duration_seconds is not None
                else max(0.0, (rec_dt - start_dt).total_seconds())
            )

            conn.execute(
                """
                UPDATE incidents
                SET resolved_at = ?, duration_seconds = ?, status = 'resolved'
                WHERE id = ?;
                """,
                (ts, dur, inc_id),
            )
            updated_cursor = conn.execute("SELECT * FROM incidents WHERE id = ?;", (inc_id,))
            updated_row = updated_cursor.fetchone()
            if updated_row:
                logger.info("Recorded recovery for target '%s' (incident #%d, duration %.1fs)", target_name, inc_id, dur)
                return self._row_to_record(updated_row)
        return None

    def get_recent_incidents(
        self,
        days: int = 7,
        limit: int = 20,
    ) -> list[IncidentRecord]:
        """Retrieve recent incident records within the given day window."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT id, target_name, target_url, started_at, resolved_at,
                   duration_seconds, error_reason, severity, status
            FROM incidents
            WHERE started_at >= ?
            ORDER BY started_at DESC
            LIMIT ?;
            """,
            (cutoff, limit),
        )
        return [self._row_to_record(row) for row in cursor.fetchall()]

    def get_active_incidents(self) -> list[IncidentRecord]:
        """Retrieve all currently unresolved ongoing incidents."""
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT id, target_name, target_url, started_at, resolved_at,
                   duration_seconds, error_reason, severity, status
            FROM incidents
            WHERE status = 'ongoing'
            ORDER BY started_at DESC;
            """
        )
        return [self._row_to_record(row) for row in cursor.fetchall()]

    def record_check_sample(
        self,
        target_name: str,
        passed: bool,
        latency_ms: float,
        checked_at: datetime | None = None,
    ) -> None:
        """Record an individual probe sample for historical SLA calculation."""
        ts = (checked_at or datetime.now(UTC)).isoformat()
        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO samples (target_name, passed, latency_ms, checked_at)
                VALUES (?, ?, ?, ?);
                """,
                (target_name, 1 if passed else 0, latency_ms, ts),
            )

    def get_historical_sla(self, days: int = 30) -> dict[str, float]:
        """Calculate historical uptime percentage per target across the days window."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT target_name,
                   COUNT(*) as total_count,
                   SUM(passed) as passed_count
            FROM samples
            WHERE checked_at >= ?
            GROUP BY target_name;
            """,
            (cutoff,),
        )
        sla_map: dict[str, float] = {}
        for row in cursor.fetchall():
            total = row["total_count"]
            passed = row["passed_count"] or 0
            sla_map[row["target_name"]] = round((passed / total) * 100.0, 2) if total > 0 else 100.0
        return sla_map

    def close(self) -> None:
        """Close SQLite database connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
