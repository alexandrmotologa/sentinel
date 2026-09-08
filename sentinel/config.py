"""Configuration models and loader for Sentinel."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Union

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


_DURATION_PATTERN = re.compile(
    r"^(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ms|s|m|h|d)?$",
    re.IGNORECASE,
)
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z0-9_]+)(?::-([^}]*))?\}")


def parse_duration(value: Union[str, int, float]) -> float:
    """Parse duration into seconds.

    Supports raw numbers or strings like '500ms', '30s', '5m', '2h', '1d'.
    """
    if isinstance(value, (int, float)):
        return float(value)

    cleaned = str(value).strip()
    match = _DURATION_PATTERN.match(cleaned)
    if not match:
        raise ValueError(f"Invalid duration format: '{value}'")

    amount = float(match.group("value"))
    unit = (match.group("unit") or "s").lower()

    if unit == "ms":
        return amount / 1000.0
    if unit == "s":
        return amount
    if unit == "m":
        return amount * 60.0
    if unit == "h":
        return amount * 3600.0
    if unit == "d":
        return amount * 86400.0

    return amount


def resolve_env_strings(val: Any) -> Any:
    """Recursively resolve environment variable references in config values.

    Handles 'env:VAR_NAME' prefix and '${VAR_NAME:-default}' placeholders.
    """
    if isinstance(val, str):
        # Check prefix format: env:VAR_NAME
        if val.startswith("env:"):
            env_key = val[4:].strip()
            return os.environ.get(env_key, "")

        # Check placeholder format: ${VAR:-default}
        def _replace_placeholder(match: re.Match[str]) -> str:
            var_name = match.group(1)
            default_val = match.group(2) if match.group(2) is not None else ""
            return os.environ.get(var_name, default_val)

        return _ENV_PATTERN.sub(_replace_placeholder, val)

    if isinstance(val, dict):
        return {k: resolve_env_strings(v) for k, v in val.items()}
    if isinstance(val, list):
        return [resolve_env_strings(item) for item in val]
    return val


class GlobalConfig(BaseModel):
    """Global daemon settings."""

    default_interval: float = Field(default=60.0, description="Default check interval in seconds")
    default_timeout: float = Field(default=10.0, description="Default request timeout in seconds")
    consecutive_failures_to_alert: int = Field(
        default=2,
        ge=1,
        description="Number of consecutive failures required before triggering an outage alert",
    )
    daily_summary_time: str | None = Field(
        default=None,
        description="Daily summary notification time in UTC (format HH:MM)",
    )

    @field_validator("default_interval", "default_timeout", mode="before")
    @classmethod
    def _validate_durations(cls, v: Any) -> float:
        return parse_duration(v)

    @field_validator("daily_summary_time")
    @classmethod
    def _validate_daily_time(cls, v: str | None) -> str | None:
        if v is None:
            return None
        parts = v.strip().split(":")
        if len(parts) != 2:
            raise ValueError("daily_summary_time must follow 'HH:MM' 24-hour format")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError:
            raise ValueError("daily_summary_time must be a valid time between 00:00 and 23:59")
        return f"{hour:02d}:{minute:02d}"


class TelegramConfig(BaseModel):
    """Telegram alerting configuration."""

    bot_token: str = Field(default="", description="Telegram Bot API token")
    chat_id: str = Field(default="", description="Telegram chat ID for alerts")
    send_silently: bool = Field(default=False, description="Send notifications without sound")
    enabled: bool = Field(default=True, description="Enable Telegram notifications")

    @property
    def is_configured(self) -> bool:
        return bool(self.enabled and self.bot_token.strip() and self.chat_id.strip())


class WebhookConfig(BaseModel):
    """Generic HTTP webhook alerting configuration."""

    url: str = Field(default="", description="Webhook destination URL for JSON payloads")
    headers: dict[str, str] = Field(default_factory=dict, description="Custom HTTP headers for webhook POST")
    enabled: bool = Field(default=True, description="Enable webhook notifications")

    @property
    def is_configured(self) -> bool:
        return bool(self.enabled and self.url.strip())


class ExpectConfig(BaseModel):
    """Assertions required for a health check to pass."""

    model_config = {"populate_by_name": True}

    status_code: Union[int, list[int], str, None] = Field(
        default=200,
        description="Expected HTTP status code, list of codes, or range string like '200-299'",
    )
    max_latency_ms: float | None = Field(
        default=None,
        description="Maximum allowed latency in milliseconds",
    )
    contains_text: str | None = Field(
        default=None,
        description="Required substring in response body",
    )
    regex: str | None = Field(
        default=None,
        description="Regular expression pattern that must match response body",
    )
    json_match: dict[str, Any] | None = Field(
        default=None,
        alias="json",
        description="Key-value assertions against response JSON body",
    )
    ssl_check: bool = Field(
        default=False,
        description="Verify SSL certificate expiration",
    )
    ssl_warn_days: int = Field(
        default=7,
        ge=1,
        description="Warn if certificate expires in fewer than this many days",
    )


class TargetConfig(BaseModel):
    """Monitored endpoint target."""

    name: str = Field(..., description="Descriptive target name")
    url: str = Field(..., description="Target URL")
    interval: float | None = Field(
        default=None,
        description="Target check interval (overrides global default)",
    )
    timeout: float | None = Field(
        default=None,
        description="Target check timeout (overrides global default)",
    )
    method: str = Field(default="GET", description="HTTP method")
    headers: dict[str, str] = Field(default_factory=dict, description="Custom HTTP headers")
    body: str | None = Field(default=None, description="Request body for POST/PUT/PATCH")
    follow_redirects: bool = Field(default=True, description="Follow HTTP redirects")
    expect: ExpectConfig = Field(default_factory=ExpectConfig, description="Health expectations")

    @field_validator("interval", "timeout", mode="before")
    @classmethod
    def _validate_target_durations(cls, v: Any) -> float | None:
        if v is None:
            return None
        return parse_duration(v)

    @field_validator("method")
    @classmethod
    def _validate_method(cls, v: str) -> str:
        return v.strip().upper()


class SentinelConfig(BaseModel):
    """Top-level Sentinel configuration file schema."""

    model_config = {"populate_by_name": True}

    global_config: GlobalConfig = Field(default_factory=GlobalConfig, alias="global")
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    targets: list[TargetConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _apply_global_defaults(self) -> SentinelConfig:
        for target in self.targets:
            if target.interval is None:
                target.interval = self.global_config.default_interval
            if target.timeout is None:
                target.timeout = self.global_config.default_timeout
        return self

    @classmethod
    def load_yaml(cls, path: Union[str, Path]) -> SentinelConfig:
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        resolved = resolve_env_strings(raw)
        return cls.model_validate(resolved)
