"""Tests for MaintenanceManager, scheduled windows, and dynamic CLI mutes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sentinel.config import MaintenanceWindowConfig
from sentinel.maintenance import MaintenanceManager


def test_scheduled_daily_window(tmp_path: Path) -> None:
    mutes_file = tmp_path / "mutes.json"
    configs = [
        MaintenanceWindowConfig(
            name="nightly-backup",
            targets=["db-master"],
            schedule="daily 02:00-04:00",
            reason="Nightly database snapshot",
        )
    ]
    mgr = MaintenanceManager(static_windows=configs, mutes_file=mutes_file)

    # During maintenance (03:15 UTC)
    t_inside = datetime(2026, 9, 17, 3, 15, 0, tzinfo=UTC)
    muted, reason = mgr.is_muted("db-master", now=t_inside)
    assert muted is True
    assert reason == "Nightly database snapshot"

    # Outside maintenance (05:00 UTC)
    t_outside = datetime(2026, 9, 17, 5, 0, 0, tzinfo=UTC)
    muted, reason = mgr.is_muted("db-master", now=t_outside)
    assert muted is False
    assert reason is None

    # Other targets not in maintenance
    muted, _ = mgr.is_muted("web-app", now=t_inside)
    assert muted is False


def test_scheduled_weekly_window(tmp_path: Path) -> None:
    mutes_file = tmp_path / "mutes.json"
    configs = [
        MaintenanceWindowConfig(
            name="sunday-maintenance",
            targets=["*"],
            schedule="weekly sun 01:00-03:00",
            reason="Weekly cluster reboot",
        )
    ]
    mgr = MaintenanceManager(static_windows=configs, mutes_file=mutes_file)

    # 2026-09-20 is a Sunday
    t_sunday_in = datetime(2026, 9, 20, 2, 0, 0, tzinfo=UTC)
    muted, reason = mgr.is_muted("any-service", now=t_sunday_in)
    assert muted is True
    assert reason == "Weekly cluster reboot"

    # 2026-09-21 is a Monday
    t_monday = datetime(2026, 9, 21, 2, 0, 0, tzinfo=UTC)
    muted, _ = mgr.is_muted("any-service", now=t_monday)
    assert muted is False


def test_scheduled_one_off_window(tmp_path: Path) -> None:
    mutes_file = tmp_path / "mutes.json"
    configs = [
        MaintenanceWindowConfig(
            name="datacenter-migration",
            targets=["legacy-api"],
            schedule="2026-10-01T12:00:00Z/2026-10-01T16:00:00Z",
            reason="Relocating servers",
        )
    ]
    mgr = MaintenanceManager(static_windows=configs, mutes_file=mutes_file)

    t_during = datetime(2026, 10, 1, 14, 0, 0, tzinfo=UTC)
    muted, reason = mgr.is_muted("legacy-api", now=t_during)
    assert muted is True
    assert reason == "Relocating servers"

    t_after = datetime(2026, 10, 1, 17, 0, 0, tzinfo=UTC)
    muted, _ = mgr.is_muted("legacy-api", now=t_after)
    assert muted is False


def test_dynamic_cli_mute_and_persistence(tmp_path: Path) -> None:
    mutes_file = tmp_path / "sentinel_mutes.json"
    mgr1 = MaintenanceManager(mutes_file=mutes_file)

    now = datetime.now(UTC)
    mgr1.mute("payment-service", duration_minutes=30, reason="Deploying v2")

    muted, reason = mgr1.is_muted("payment-service", now=now)
    assert muted is True
    assert reason == "Deploying v2"

    active = mgr1.get_active_mutes(now=now)
    assert len(active) == 1
    assert active[0].target_name == "payment-service"

    # Persistence verification in new manager instance
    mgr2 = MaintenanceManager(mutes_file=mutes_file)
    muted, reason = mgr2.is_muted("payment-service", now=now)
    assert muted is True

    # Unmute
    assert mgr2.unmute("payment-service") is True
    assert mgr2.unmute("payment-service") is False  # Already unmuted
    muted_after_unmute, _ = mgr2.is_muted("payment-service", now=now)
    assert muted_after_unmute is False

    # Check expiration on temporary target
    mgr2.mute("temp-service", duration_minutes=10, reason="Short test")
    assert mgr2.is_muted("temp-service", now=now)[0] is True
    assert mgr2.is_muted("temp-service", now=now + timedelta(minutes=15))[0] is False
