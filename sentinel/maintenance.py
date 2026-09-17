"""Maintenance windows, schedule evaluation, and dynamic target muting."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sentinel.config import MaintenanceWindowConfig

logger = logging.getLogger("sentinel.maintenance")

_DAILY_PATTERN = re.compile(
    r"^(?:daily\s+)?(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})(?:\s*utc)?$",
    re.IGNORECASE,
)
_WEEKLY_PATTERN = re.compile(
    r"^(?:weekly\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)s?\s+(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})(?:\s*utc)?$",
    re.IGNORECASE,
)
_ONE_OFF_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2})\s*(?:to|-)\s*(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2})(?:\s*utc)?$",
    re.IGNORECASE,
)

_DAY_ALIASES = {
    "mon": 0, "monday": 0,
    "tue": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}


@dataclass
class ActiveMute:
    """Represents an active in-memory or persisted target maintenance mute."""

    target_name: str
    muted_at: datetime
    expires_at: datetime
    reason: str

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)


class MaintenanceManager:
    """Evaluates scheduled maintenance rules and persists dynamic target mutes."""

    def __init__(
        self,
        windows: list[MaintenanceWindowConfig] | None = None,
        static_windows: list[MaintenanceWindowConfig] | None = None,
        mutes_file: Path | str | None = None,
    ) -> None:
        self.windows = windows or static_windows or []
        if mutes_file is not None:
            self.mutes_file = Path(mutes_file)
        else:
            env_path = os.environ.get("SENTINEL_MUTES_PATH")
            if env_path:
                self.mutes_file = Path(env_path)
            else:
                sentinel_home = Path.home() / ".sentinel"
                self.mutes_file = sentinel_home / "mutes.json"

        self.mutes_file.parent.mkdir(parents=True, exist_ok=True)

    def _read_mutes(self) -> dict[str, dict[str, Any]]:
        """Read dynamic mutes dictionary from local JSON storage."""
        if not self.mutes_file.exists():
            return {}
        try:
            with open(self.mutes_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.debug("Failed reading mutes file: %s", exc)
            return {}

    def _write_mutes(self, mutes: dict[str, dict[str, Any]]) -> None:
        """Atomically persist dynamic mutes dictionary to disk."""
        try:
            temp_path = self.mutes_file.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(mutes, f, indent=2)
            temp_path.replace(self.mutes_file)
        except Exception as exc:
            logger.warning("Failed writing mutes file: %s", exc)

    def mute(
        self,
        target_name: str,
        duration_seconds: float = 3600.0,
        duration_minutes: float | None = None,
        reason: str = "Manual mute via CLI",
    ) -> None:
        """Mute a target for duration_seconds or duration_minutes."""
        if duration_minutes is not None:
            duration_seconds = duration_minutes * 60.0

        mutes = self._read_mutes()
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=max(1.0, duration_seconds))
        mutes[target_name] = {
            "target": target_name,
            "muted_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "reason": reason,
        }
        self._write_mutes(mutes)
        logger.info("Target '%s' muted for %.0fs: %s", target_name, duration_seconds, reason)

    def unmute(self, target_name: str) -> bool:
        """Remove dynamic mute for target_name. Return True if found and removed."""
        mutes = self._read_mutes()
        if target_name in mutes:
            del mutes[target_name]
            self._write_mutes(mutes)
            logger.info("Target '%s' unmuted", target_name)
            return True
        return False

    def get_active_mutes(self, now: datetime | None = None) -> list[ActiveMute]:
        """Retrieve all currently active dynamic mutes as typed ActiveMute items."""
        mutes = self._read_mutes()
        current = now or datetime.now(UTC)
        active: list[ActiveMute] = []
        modified = False

        for target_name, info in list(mutes.items()):
            try:
                expires_at = datetime.fromisoformat(info["expires_at"])
                if expires_at > current:
                    muted_at = (
                        datetime.fromisoformat(info["muted_at"])
                        if "muted_at" in info
                        else current
                    )
                    active.append(
                        ActiveMute(
                            target_name=target_name,
                            muted_at=muted_at,
                            expires_at=expires_at,
                            reason=info.get("reason", "Maintenance"),
                        )
                    )
                else:
                    del mutes[target_name]
                    modified = True
            except Exception:
                del mutes[target_name]
                modified = True

        if modified:
            self._write_mutes(mutes)

        return active

    def is_muted(
        self,
        target_name: str,
        now: datetime | None = None,
    ) -> tuple[bool, str | None]:
        """Check if target is currently muted via dynamic mute or scheduled window.

        Returns:
            Tuple of (is_muted_bool, reason_string_or_None).
        """
        current = now or datetime.now(UTC)

        # 1. Check dynamic mutes
        active_mutes = self.get_active_mutes(current)
        for m in active_mutes:
            if m.target_name == target_name or m.target_name == "*":
                return True, m.reason

        # 2. Check static scheduled maintenance windows
        for window in self.windows:
            targets = window.targets if window.targets else [window.target]
            if "*" not in targets and target_name not in targets:
                continue

            if self._matches_schedule(window.schedule, current):
                return True, window.reason

        return False, None

    @staticmethod
    def _matches_schedule(schedule: str, now: datetime) -> bool:
        """Evaluate if the current datetime falls within the schedule expression."""
        clean = schedule.strip()

        # Check ISO range with slash: 2026-10-01T12:00:00Z/2026-10-01T16:00:00Z
        if "/" in clean:
            parts = clean.split("/")
            if len(parts) == 2:
                try:
                    start_str = parts[0].replace("Z", "+00:00")
                    end_str = parts[1].replace("Z", "+00:00")
                    start_dt = datetime.fromisoformat(start_str)
                    end_dt = datetime.fromisoformat(end_str)
                    return start_dt <= now < end_dt
                except Exception:
                    pass

        # Check weekly format: 'weekly sun 01:00-03:00' or 'saturdays 01:00-03:00 UTC'
        weekly_match = _WEEKLY_PATTERN.match(clean)
        if weekly_match:
            day_str = weekly_match.group(1).lower()
            expected_weekday = _DAY_ALIASES.get(day_str)
            if expected_weekday is not None and now.weekday() == expected_weekday:
                sh, sm, eh, em = (
                    int(weekly_match.group(2)),
                    int(weekly_match.group(3)),
                    int(weekly_match.group(4)),
                    int(weekly_match.group(5)),
                )
                start_minute = sh * 60 + sm
                end_minute = eh * 60 + em
                current_minute = now.hour * 60 + now.minute
                return start_minute <= current_minute < end_minute
            return False

        # Check daily format: 'daily 02:00-03:00 UTC'
        daily_match = _DAILY_PATTERN.match(clean)
        if daily_match:
            sh, sm, eh, em = map(int, daily_match.groups())
            start_minute = sh * 60 + sm
            end_minute = eh * 60 + em
            current_minute = now.hour * 60 + now.minute
            if start_minute <= end_minute:
                return start_minute <= current_minute < end_minute
            # Overnight window (e.g. 23:00 - 02:00)
            return current_minute >= start_minute or current_minute < end_minute

        # Check one-off ISO range: '2026-09-20 02:00 to 2026-09-20 04:00'
        one_off_match = _ONE_OFF_PATTERN.match(clean)
        if one_off_match:
            try:
                start_dt = datetime.strptime(one_off_match.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
                end_dt = datetime.strptime(one_off_match.group(2), "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
                return start_dt <= now < end_dt
            except Exception:
                return False

        return False
