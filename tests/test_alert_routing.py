"""Tests for per-target notification channel routing and severity badges."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from sentinel.notifier import AlertDispatcher, BaseNotifier
from sentinel.state import TargetState


class SpyNotifier(BaseNotifier):
    """Spy notifier for tracking sent outage and recovery alerts."""

    def __init__(self, channel_id: str) -> None:
        self.channel_id = channel_id
        self.outages: list[dict[str, Any]] = []
        self.recoveries: list[dict[str, Any]] = []

    @property
    def is_configured(self) -> bool:
        return True

    async def send_outage_alert(
        self,
        state: TargetState,
        debounce_threshold: int,
        timestamp: datetime | None = None,
        severity: str = "critical",
    ) -> bool:
        self.outages.append({
            "target": state.name,
            "threshold": debounce_threshold,
            "severity": severity,
            "timestamp": timestamp,
        })
        return True

    async def send_recovery_alert(
        self,
        state: TargetState,
        timestamp: datetime | None = None,
        severity: str = "critical",
    ) -> bool:
        self.recoveries.append({
            "target": state.name,
            "severity": severity,
            "timestamp": timestamp,
        })
        return True

    async def send_test_alert(self) -> bool:
        return True

    async def send_daily_summary(
        self,
        states: list[TargetState],
        timestamp: datetime | None = None,
    ) -> bool:
        return True


@pytest.mark.asyncio
async def test_alert_routing_selective_channels() -> None:
    dispatcher = AlertDispatcher()
    tg = SpyNotifier("telegram")
    wh = SpyNotifier("webhook")
    dc = SpyNotifier("discord")
    sl = SpyNotifier("slack")

    dispatcher.register(tg)
    dispatcher.register(wh)
    dispatcher.register(dc)
    dispatcher.register(sl)

    state = TargetState(name="payment-gateway", url="https://pay.example.com")
    now = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)

    # 1. Route only to telegram and slack
    sent = await dispatcher.send_outage_alert(
        state=state,
        debounce_threshold=2,
        timestamp=now,
        channels=["telegram", "slack"],
        severity="critical",
    )
    assert sent is True
    assert len(tg.outages) == 1
    assert len(sl.outages) == 1
    assert len(wh.outages) == 0
    assert len(dc.outages) == 0

    # 2. Route with severity "warning" to webhook only
    sent_wh = await dispatcher.send_outage_alert(
        state=state,
        debounce_threshold=1,
        timestamp=now,
        channels=["webhook"],
        severity="warning",
    )
    assert sent_wh is True
    assert len(wh.outages) == 1
    assert wh.outages[0]["severity"] == "warning"

    # 3. Route recovery alert
    await dispatcher.send_recovery_alert(
        state=state,
        timestamp=now,
        channels=["telegram"],
        severity="warning",
    )
    assert len(tg.recoveries) == 1
    assert tg.recoveries[0]["severity"] == "warning"


@pytest.mark.asyncio
async def test_alert_routing_default_fallback_to_all() -> None:
    dispatcher = AlertDispatcher()
    tg = SpyNotifier("telegram")
    wh = SpyNotifier("webhook")
    dispatcher.register(tg)
    dispatcher.register(wh)

    state = TargetState(name="auth-service", url="https://auth.example.com")

    # When channels is None or empty, should broadcast to all configured channels
    await dispatcher.send_outage_alert(state, debounce_threshold=2, channels=None)
    assert len(tg.outages) == 1
    assert len(wh.outages) == 1

    await dispatcher.send_outage_alert(state, debounce_threshold=2, channels=[])
    assert len(tg.outages) == 2
    assert len(wh.outages) == 2
