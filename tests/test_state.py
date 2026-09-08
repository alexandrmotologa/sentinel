"""Unit tests for TargetState, debounce protection, and downtime arithmetic."""

from datetime import datetime, timedelta, timezone

from sentinel.evaluator import CheckResult
from sentinel.state import TargetState, TargetStatus, format_duration


def test_format_duration():
    assert format_duration(0) == "< 1 second"
    assert format_duration(45) == "45 seconds"
    assert format_duration(60) == "1 minute"
    assert format_duration(95) == "1 minute, 35 seconds"
    assert format_duration(3665) == "1 hour, 1 minute, 5 seconds"


def test_state_debounce_and_recovery():
    state = TargetState(name="Test Target", url="https://test.com")
    assert state.status == TargetStatus.UNKNOWN
    assert state.consecutive_failures == 0

    base_time = datetime(2026, 9, 9, 10, 0, 0, tzinfo=timezone.utc)

    # 1. First failure: within debounce window (threshold=2), no outage alert yet
    fail_1 = CheckResult(
        passed=False,
        status_code=500,
        status_phrase="Server Error",
        latency_ms=250.0,
        error_reason="500 Internal Server Error",
        checked_at=base_time,
    )
    should_outage, should_recovery = state.update(fail_1, debounce_threshold=2)
    assert not should_outage
    assert not should_recovery
    assert state.consecutive_failures == 1
    assert state.down_since == base_time
    assert not state.alert_sent

    # 2. Second failure: reaches debounce threshold -> trigger outage alert!
    fail_2 = CheckResult(
        passed=False,
        status_code=500,
        status_phrase="Server Error",
        latency_ms=300.0,
        error_reason="500 Internal Server Error",
        checked_at=base_time + timedelta(seconds=30),
    )
    should_outage, should_recovery = state.update(fail_2, debounce_threshold=2)
    assert should_outage
    assert not should_recovery
    assert state.consecutive_failures == 2
    assert state.status == TargetStatus.DOWN
    assert state.alert_sent

    # 3. Third failure: remains down, but do NOT re-alert (flap protection)
    fail_3 = CheckResult(
        passed=False,
        status_code=500,
        status_phrase="Server Error",
        latency_ms=290.0,
        error_reason="500 Internal Server Error",
        checked_at=base_time + timedelta(seconds=60),
    )
    should_outage, should_recovery = state.update(fail_3, debounce_threshold=2)
    assert not should_outage
    assert not should_recovery
    assert state.consecutive_failures == 3
    assert state.status == TargetStatus.DOWN

    # 4. Service recovers: trigger recovery alert!
    recovery = CheckResult(
        passed=True,
        status_code=200,
        status_phrase="OK",
        latency_ms=80.0,
        checked_at=base_time + timedelta(seconds=120),
    )
    should_outage, should_recovery = state.update(recovery, debounce_threshold=2)
    assert not should_outage
    assert should_recovery
    assert state.status == TargetStatus.UP
    assert state.consecutive_failures == 0
    assert not state.alert_sent
    assert state.previous_downtime_seconds == 120.0


def test_transient_blip_does_not_send_recovery():
    state = TargetState(name="Blip Target", url="https://blip.com")
    base_time = datetime(2026, 9, 9, 10, 0, 0, tzinfo=timezone.utc)

    # Single failure (threshold=2)
    fail = CheckResult(
        passed=False,
        status_code=502,
        status_phrase="Bad Gateway",
        latency_ms=100.0,
        error_reason="502 Bad Gateway",
        checked_at=base_time,
    )
    should_outage, should_recovery = state.update(fail, debounce_threshold=2)
    assert not should_outage
    assert not should_recovery

    # Next check passes -> recovery alert must NOT be sent since no outage alert went out
    ok = CheckResult(
        passed=True,
        status_code=200,
        status_phrase="OK",
        latency_ms=50.0,
        checked_at=base_time + timedelta(seconds=15),
    )
    should_outage, should_recovery = state.update(ok, debounce_threshold=2)
    assert not should_outage
    assert not should_recovery
    assert state.status == TargetStatus.UP


def test_uptime_percentage():
    state = TargetState(name="Uptime Target", url="https://uptime.com")
    assert state.uptime_percentage == 100.0

    state.total_checks = 10
    state.successful_checks = 9
    assert state.uptime_percentage == 90.0


def test_latency_statistics():
    state = TargetState(name="Latency Target", url="https://latency.com")
    assert state.average_latency_ms == 0.0

    r1 = CheckResult(passed=True, status_code=200, status_phrase="OK", latency_ms=100.0)
    r2 = CheckResult(passed=True, status_code=200, status_phrase="OK", latency_ms=200.0)
    r3 = CheckResult(passed=True, status_code=200, status_phrase="OK", latency_ms=300.0)

    state.update(r1, debounce_threshold=2)
    state.update(r2, debounce_threshold=2)
    state.update(r3, debounce_threshold=2)

    assert state.min_latency_ms == 100.0
    assert state.max_latency_ms == 300.0
    assert state.average_latency_ms == 200.0
