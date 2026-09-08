"""State tracking, flap protection, and downtime arithmetic for targets."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from sentinel.evaluator import CheckResult


class TargetStatus(str, Enum):
    """Current operational health status."""

    UNKNOWN = "UNKNOWN"
    UP = "UP"
    DOWN = "DOWN"


def format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration string."""
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
    """In-memory state and history for a monitored target."""

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

    @property
    def uptime_percentage(self) -> float:
        if self.total_checks == 0:
            return 100.0
        return (self.successful_checks / self.total_checks) * 100.0

    def get_downtime_seconds(self, now: datetime | None = None) -> float:
        if self.down_since is None:
            return 0.0
        current = now or datetime.now(timezone.utc)
        return max(0.0, (current - self.down_since).total_seconds())

    def update(
        self,
        result: CheckResult,
        debounce_threshold: int,
    ) -> tuple[bool, bool]:
        """Update target state with a new check result.

        Returns:
            A tuple of (should_send_outage_alert, should_send_recovery_alert).
        """
        now = result.checked_at
        self.total_checks += 1
        self.last_checked_at = now
        self.last_latency_ms = result.latency_ms
        self.last_status_code = result.status_code
        self.last_status_phrase = result.status_phrase

        should_send_outage = False
        should_send_recovery = False

        if result.passed:
            self.successful_checks += 1
            self.last_error_reason = None
            self.consecutive_failures = 0

            if self.alert_sent and self.down_since is not None:
                # Target was previously confirmed down and alerted
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
                self.status = TargetStatus.DOWN
                self.alert_sent = True
                should_send_outage = True
            elif self.consecutive_failures > debounce_threshold:
                self.status = TargetStatus.DOWN
                # Already alerted, keep state down without re-alerting

        return should_send_outage, should_send_recovery
