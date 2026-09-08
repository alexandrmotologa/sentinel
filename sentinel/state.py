"""Target state tracking, health metrics, and flap-protected state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentinel.evaluator import CheckResult


class TargetStatus(str, Enum):
    """Operational health status of a monitored target."""

    UNKNOWN = "UNKNOWN"
    UP = "UP"
    DOWN = "DOWN"


def format_duration(seconds: float) -> str:
    """Format duration in seconds into human-readable text (e.g. '1 hour, 2 minutes')."""
    total_seconds = max(0, int(seconds))
    if total_seconds == 0:
        return "< 1 second"

    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    parts: list[str] = []
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if secs > 0 or not parts:
        parts.append(f"{secs} second{'s' if secs != 1 else ''}")

    return ", ".join(parts)


@dataclass
class TargetState:
    """Maintains in-memory health metrics, history, and flap-protected transitions for a target."""

    name: str
    url: str
    status: TargetStatus = TargetStatus.UNKNOWN
    consecutive_failures: int = 0
    down_since: datetime | None = None
    last_latency_ms: float = 0.0
    last_status_code: int | None = None
    last_status_phrase: str = ""
    last_error_reason: str | None = None
    alert_sent: bool = False
    total_checks: int = 0
    successful_checks: int = 0
    last_checked_at: datetime | None = None
    previous_downtime_seconds: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    total_latency_ms: float = 0.0

    @property
    def uptime_percentage(self) -> float:
        """Percentage of health checks that passed successfully."""
        if self.total_checks == 0:
            return 100.0
        return (self.successful_checks / self.total_checks) * 100.0

    @property
    def average_latency_ms(self) -> float:
        """Cumulative arithmetic mean latency in milliseconds."""
        if self.total_checks == 0:
            return 0.0
        return self.total_latency_ms / self.total_checks

    def get_downtime_seconds(self, now: datetime | None = None) -> float:
        """Calculate elapsed downtime in seconds if currently down."""
        if self.down_since is None:
            return 0.0
        current = now or datetime.now(timezone.utc)
        return max(0.0, (current - self.down_since).total_seconds())

    def record_latency(self, latency_ms: float) -> None:
        """Record latency sample and update min/max/average statistics."""
        self.last_latency_ms = latency_ms
        self.total_latency_ms += latency_ms
        if self.total_checks == 1 or latency_ms < self.min_latency_ms:
            self.min_latency_ms = latency_ms
        if latency_ms > self.max_latency_ms:
            self.max_latency_ms = latency_ms

    def update(
        self,
        result: CheckResult,
        debounce_threshold: int,
    ) -> tuple[bool, bool]:
        """Update target state with a check outcome applying debouncing and flap protection.

        Args:
            result: The CheckResult from a completed probe evaluation.
            debounce_threshold: Number of consecutive failures before declaring DOWN and alerting.

        Returns:
            A tuple of (should_send_outage_alert, should_send_recovery_alert).
        """
        now = result.checked_at
        self.total_checks += 1
        self.last_checked_at = now
        self.record_latency(result.latency_ms)

        self.last_status_code = result.status_code
        self.last_status_phrase = result.status_phrase

        should_send_outage = False
        should_send_recovery = False

        if result.passed:
            self.successful_checks += 1
            self.last_error_reason = None
            self.consecutive_failures = 0

            if self.alert_sent and self.down_since is not None:
                # Target was previously confirmed down and alerted; transition to UP with recovery alert
                self.previous_downtime_seconds = (now - self.down_since).total_seconds()
                should_send_recovery = True
                self.alert_sent = False
                self.down_since = None
                self.status = TargetStatus.UP
            else:
                self.status = TargetStatus.UP
                self.down_since = None
        else:
            self.consecutive_failures += 1
            self.last_error_reason = result.error_reason

            if self.down_since is None:
                self.down_since = now

            if self.consecutive_failures == debounce_threshold:
                # Debounce threshold reached: mark DOWN and trigger single outage notification
                self.status = TargetStatus.DOWN
                self.alert_sent = True
                should_send_outage = True
            elif self.consecutive_failures > debounce_threshold:
                # Flap protection: stay DOWN but do not re-trigger alerts
                self.status = TargetStatus.DOWN

        return should_send_outage, should_send_recovery
