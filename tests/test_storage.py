"""Tests for SQLite-backed persistent incident storage and SLA tracking."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sentinel.storage import IncidentStore


def test_incident_store_lifecycle(tmp_path: Path) -> None:
    db_file = tmp_path / "test_sentinel.db"
    store = IncidentStore(db_file)

    # Verify tables and WAL mode
    with sqlite3.connect(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        assert "incidents" in tables
        assert "samples" in tables

        cursor.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode.lower() == "wal"

    # 1. Record an outage start
    start_time = datetime(2026, 9, 17, 10, 0, 0, tzinfo=UTC)
    inc_id = store.record_outage_start(
        target_name="api-gateway",
        error_reason="Connection refused (port 8080)",
        started_at=start_time,
    )
    assert inc_id > 0

    # Verify active incidents
    active = store.get_active_incidents()
    assert len(active) == 1
    assert active[0].target_name == "api-gateway"
    assert active[0].error_reason == "Connection refused (port 8080)"
    assert active[0].resolved_at is None
    assert active[0].duration_seconds is None

    # Idempotent call should return existing ongoing incident id
    second_id = store.record_outage_start(
        target_name="api-gateway",
        error_reason="Another failure",
        started_at=start_time + timedelta(minutes=1),
    )
    assert second_id == inc_id

    # 2. Record recovery
    recovery_time = datetime(2026, 9, 17, 10, 15, 30, tzinfo=UTC)
    recovered_inc = store.record_recovery("api-gateway", recovered_at=recovery_time)
    assert recovered_inc is not None
    assert recovered_inc.id == inc_id
    assert recovered_inc.resolved_at == recovery_time
    assert recovered_inc.duration_seconds == 930.0  # 15m 30s

    # No more active incidents
    assert len(store.get_active_incidents()) == 0

    # 3. Query recent incidents
    recent = store.get_recent_incidents(days=7)
    assert len(recent) == 1
    assert recent[0].target_name == "api-gateway"
    assert recent[0].duration_seconds == 930.0

    # 4. Sampling & SLA calculations
    now = datetime.now(UTC)
    for i in range(10):
        store.record_check_sample(
            target_name="api-gateway",
            passed=(i < 9),  # 9 passes, 1 failure = 90%
            latency_ms=25.0,
            checked_at=now - timedelta(minutes=i),
        )

    sla = store.get_historical_sla(days=1)
    assert "api-gateway" in sla
    assert sla["api-gateway"] == 90.0

    store.close()
