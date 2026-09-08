"""Telegram notification client with HTML templating and retry handling."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import html
import logging
from typing import Any

import httpx

from sentinel.config import TelegramConfig
from sentinel.state import TargetState, format_duration


logger = logging.getLogger("sentinel.notifier")


class TelegramNotifier:
    """Delivers formatted monitoring alerts via Telegram Bot API."""

    def __init__(self, config: TelegramConfig | None = None) -> None:
        self.config = config or TelegramConfig()
        self._api_base = f"https://api.telegram.org/bot{self.config.bot_token or ''}"

    async def send_message(
        self,
        text: str,
        disable_notification: bool = False,
        max_retries: int = 3,
    ) -> bool:
        """Send an HTML-formatted message to the configured Telegram chat."""
        if not self.config.is_configured:
            logger.debug("Telegram is not configured; skipping notification.")
            return False

        url = f"{self._api_base}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": self.config.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "disable_notification": disable_notification,
        }

        delay = 1.0
        async with httpx.AsyncClient(timeout=10.0) as client:
            for attempt in range(1, max_retries + 1):
                try:
                    response = await client.post(url, json=payload)
                    if response.is_success:
                        return True

                    data = response.json()
                    desc = data.get("description", response.text)
                    logger.warning(
                        "Telegram API error (attempt %d/%d): %s %s",
                        attempt,
                        max_retries,
                        response.status_code,
                        desc,
                    )
                except Exception as exc:
                    logger.warning(
                        "Network error delivering Telegram message (attempt %d/%d): %s",
                        attempt,
                        max_retries,
                        exc,
                    )

                if attempt < max_retries:
                    await asyncio.sleep(delay)
                    delay *= 2.0

        return False

    async def send_outage_alert(
        self,
        state: TargetState,
        debounce_threshold: int,
        timestamp: datetime | None = None,
    ) -> bool:
        """Send an outage alert when a target fails health checks."""
        ts = timestamp or datetime.now(timezone.utc)
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")

        status_text = (
            f"{state.last_status_code} {state.last_status_phrase}".strip()
            if state.last_status_code is not None
            else (state.last_status_phrase or "Unavailable")
        )

        reason_escaped = html.escape(state.last_error_reason or "Health check failed")
        name_escaped = html.escape(state.name)
        url_escaped = html.escape(state.url)
        status_escaped = html.escape(status_text)

        message = (
            f"🚨 <b>SERVICE DOWN: {name_escaped}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>URL:</b> <code>{url_escaped}</code>\n"
            f"<b>Reason:</b> ❌ {reason_escaped}\n"
            f"<b>HTTP Status:</b> {status_escaped}\n"
            f"<b>Response Latency:</b> {int(state.last_latency_ms):,} ms\n"
            f"<b>Consecutive Failures:</b> {state.consecutive_failures} / {debounce_threshold}\n"
            f"<b>Timestamp:</b> {ts_str} UTC"
        )

        return await self.send_message(message, disable_notification=False)

    async def send_recovery_alert(
        self,
        state: TargetState,
        timestamp: datetime | None = None,
    ) -> bool:
        """Send a recovery alert when a failing target returns to healthy status."""
        ts = timestamp or datetime.now(timezone.utc)
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")

        duration_str = format_duration(state.previous_downtime_seconds)
        status_text = (
            f"{state.last_status_code} {state.last_status_phrase}".strip()
            if state.last_status_code is not None
            else "200 OK"
        )

        name_escaped = html.escape(state.name)
        url_escaped = html.escape(state.url)
        status_escaped = html.escape(status_text)

        message = (
            f"✅ <b>SERVICE RECOVERED: {name_escaped}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>URL:</b> <code>{url_escaped}</code>\n"
            f"<b>Downtime Duration:</b> {duration_str}\n"
            f"<b>Current Status:</b> {status_escaped}\n"
            f"<b>Current Latency:</b> {int(state.last_latency_ms):,} ms\n"
            f"<b>Timestamp:</b> {ts_str} UTC"
        )

        silent = self.config.send_silently
        return await self.send_message(message, disable_notification=silent)

    async def send_test_alert(self) -> bool:
        """Send a test message verifying Telegram credentials."""
        ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        message = (
            "🔍 <b>SENTINEL TEST ALERT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Status:</b> ✅ Monitoring daemon alert delivery verified\n"
            f"<b>Timestamp:</b> {ts_str} UTC"
        )
        return await self.send_message(message, disable_notification=False)

    async def send_daily_summary(
        self,
        states: list[TargetState],
        timestamp: datetime | None = None,
    ) -> bool:
        """Send a daily health summary report."""
        ts = timestamp or datetime.now(timezone.utc)
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")

        total = len(states)
        healthy = sum(1 for s in states if s.status.value == "UP")
        avg_uptime = (sum(s.uptime_percentage for s in states) / total) if total > 0 else 100.0

        rows: list[str] = []
        for s in states:
            icon = "🟢" if s.status.value == "UP" else "🔴"
            rows.append(
                f"{icon} <b>{html.escape(s.name)}</b>: {s.uptime_percentage:.1f}% uptime "
                f"({int(s.last_latency_ms)} ms)"
            )

        breakdown = "\n".join(rows)
        message = (
            "📊 <b>SENTINEL DAILY SUMMARY</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Monitored Services:</b> {total}\n"
            f"<b>Healthy Services:</b> {healthy}\n"
            f"<b>Average Uptime:</b> {avg_uptime:.2f}%\n"
            f"<b>Timestamp:</b> {ts_str} UTC\n\n"
            f"{breakdown}"
        )

        return await self.send_message(message, disable_notification=self.config.send_silently)


class WebhookNotifier:
    """Delivers structured JSON alerts to generic HTTP webhooks."""

    def __init__(self, config: Any) -> None:
        self.config = config

    async def send_webhook(
        self,
        payload: dict[str, Any],
        max_retries: int = 3,
    ) -> bool:
        if not getattr(self.config, "is_configured", False):
            return False

        url = self.config.url
        headers = {"Content-Type": "application/json", **self.config.headers}
        delay = 1.0

        async with httpx.AsyncClient(timeout=10.0) as client:
            for attempt in range(1, max_retries + 1):
                try:
                    response = await client.post(url, json=payload, headers=headers)
                    if response.is_success:
                        return True
                    logger.warning(
                        "Webhook returned status %d on attempt %d/%d",
                        response.status_code,
                        attempt,
                        max_retries,
                    )
                except Exception as exc:
                    logger.warning(
                        "Webhook delivery error (attempt %d/%d): %s",
                        attempt,
                        max_retries,
                        exc,
                    )

                if attempt < max_retries:
                    await asyncio.sleep(delay)
                    delay *= 2.0

        return False


class DiscordNotifier:
    """Delivers rich embed alerts to Discord webhooks."""

    def __init__(self, config: Any) -> None:
        self.config = config

    async def send_message(self, payload: dict[str, Any], max_retries: int = 3) -> bool:
        if not getattr(self.config, "is_configured", False):
            return False

        url = self.config.webhook_url
        delay = 1.0
        async with httpx.AsyncClient(timeout=10.0) as client:
            for attempt in range(1, max_retries + 1):
                try:
                    res = await client.post(url, json=payload)
                    if res.is_success:
                        return True
                    logger.warning("Discord webhook returned status %d", res.status_code)
                except Exception as exc:
                    logger.warning("Discord delivery error: %s", exc)

                if attempt < max_retries:
                    await asyncio.sleep(delay)
                    delay *= 2.0
        return False

    async def send_outage_alert(
        self, state: TargetState, debounce_threshold: int, timestamp: datetime | None = None
    ) -> bool:
        ts = timestamp or datetime.now(timezone.utc)
        payload = {
            "username": getattr(self.config, "username", "Sentinel"),
            "avatar_url": getattr(self.config, "avatar_url", None) or None,
            "embeds": [
                {
                    "title": f"🚨 SERVICE DOWN: {state.name}",
                    "description": f"Health check failed for `{state.name}`.",
                    "color": 15158332,
                    "fields": [
                        {"name": "URL", "value": f"`{state.url}`", "inline": False},
                        {"name": "Reason", "value": state.last_error_reason or "Failed", "inline": False},
                        {"name": "HTTP Status", "value": str(state.last_status_code or "N/A"), "inline": True},
                        {"name": "Latency", "value": f"{int(state.last_latency_ms)} ms", "inline": True},
                        {"name": "Consecutive Failures", "value": f"{state.consecutive_failures} / {debounce_threshold}", "inline": True},
                    ],
                    "timestamp": ts.isoformat(),
                }
            ],
        }
        return await self.send_message(payload)

    async def send_recovery_alert(self, state: TargetState, timestamp: datetime | None = None) -> bool:
        ts = timestamp or datetime.now(timezone.utc)
        duration_str = format_duration(state.previous_downtime_seconds)
        payload = {
            "username": getattr(self.config, "username", "Sentinel"),
            "avatar_url": getattr(self.config, "avatar_url", None) or None,
            "embeds": [
                {
                    "title": f"✅ SERVICE RECOVERED: {state.name}",
                    "description": f"Service `{state.name}` has recovered.",
                    "color": 3066993,
                    "fields": [
                        {"name": "URL", "value": f"`{state.url}`", "inline": False},
                        {"name": "Downtime Duration", "value": duration_str, "inline": True},
                        {"name": "Current Latency", "value": f"{int(state.last_latency_ms)} ms", "inline": True},
                    ],
                    "timestamp": ts.isoformat(),
                }
            ],
        }
        return await self.send_message(payload)

    async def send_test_alert(self) -> bool:
        payload = {
            "username": getattr(self.config, "username", "Sentinel"),
            "embeds": [
                {
                    "title": "🔍 SENTINEL TEST ALERT",
                    "description": "Discord webhook delivery verified successfully.",
                    "color": 3447003,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ],
        }
        return await self.send_message(payload)

    async def send_daily_summary(self, states: list[TargetState], timestamp: datetime | None = None) -> bool:
        ts = timestamp or datetime.now(timezone.utc)
        total = len(states)
        healthy = sum(1 for s in states if s.status.value == "UP")
        avg_uptime = (sum(s.uptime_percentage for s in states) / total) if total > 0 else 100.0

        rows = [f"• **{s.name}**: {s.uptime_percentage:.1f}% uptime ({int(s.last_latency_ms)}ms)" for s in states]
        payload = {
            "username": getattr(self.config, "username", "Sentinel"),
            "embeds": [
                {
                    "title": "📊 SENTINEL DAILY SUMMARY",
                    "description": "\n".join(rows),
                    "color": 3447003,
                    "fields": [
                        {"name": "Total Monitored", "value": str(total), "inline": True},
                        {"name": "Healthy", "value": str(healthy), "inline": True},
                        {"name": "Average Uptime", "value": f"{avg_uptime:.2f}%", "inline": True},
                    ],
                    "timestamp": ts.isoformat(),
                }
            ],
        }
        return await self.send_message(payload)


class SlackNotifier:
    """Delivers Block Kit alerts to Slack incoming webhooks."""

    def __init__(self, config: Any) -> None:
        self.config = config

    async def send_message(self, payload: dict[str, Any], max_retries: int = 3) -> bool:
        if not getattr(self.config, "is_configured", False):
            return False

        url = self.config.webhook_url
        delay = 1.0
        async with httpx.AsyncClient(timeout=10.0) as client:
            for attempt in range(1, max_retries + 1):
                try:
                    res = await client.post(url, json=payload)
                    if res.is_success:
                        return True
                    logger.warning("Slack webhook returned status %d", res.status_code)
                except Exception as exc:
                    logger.warning("Slack delivery error: %s", exc)

                if attempt < max_retries:
                    await asyncio.sleep(delay)
                    delay *= 2.0
        return False

    async def send_outage_alert(
        self, state: TargetState, debounce_threshold: int, timestamp: datetime | None = None
    ) -> bool:
        payload = {
            "text": f"🚨 SERVICE DOWN: {state.name}",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"🚨 SERVICE DOWN: {state.name}"},
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*URL:*\n`{state.url}`"},
                        {"type": "mrkdwn", "text": f"*HTTP Status:*\n{state.last_status_code or 'N/A'}"},
                        {"type": "mrkdwn", "text": f"*Reason:*\n{state.last_error_reason or 'Failure'}"},
                        {"type": "mrkdwn", "text": f"*Failures:*\n{state.consecutive_failures} / {debounce_threshold}"},
                    ],
                },
            ],
        }
        return await self.send_message(payload)

    async def send_recovery_alert(self, state: TargetState, timestamp: datetime | None = None) -> bool:
        duration_str = format_duration(state.previous_downtime_seconds)
        payload = {
            "text": f"✅ SERVICE RECOVERED: {state.name}",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"✅ SERVICE RECOVERED: {state.name}"},
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*URL:*\n`{state.url}`"},
                        {"type": "mrkdwn", "text": f"*Downtime Duration:*\n{duration_str}"},
                        {"type": "mrkdwn", "text": f"*Current Latency:*\n{int(state.last_latency_ms)} ms"},
                    ],
                },
            ],
        }
        return await self.send_message(payload)

    async def send_test_alert(self) -> bool:
        payload = {
            "text": "🔍 SENTINEL TEST ALERT",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "🔍 SENTINEL TEST ALERT"},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "Slack webhook alert delivery verified."},
                },
            ],
        }
        return await self.send_message(payload)

    async def send_daily_summary(self, states: list[TargetState], timestamp: datetime | None = None) -> bool:
        total = len(states)
        healthy = sum(1 for s in states if s.status.value == "UP")
        avg_uptime = (sum(s.uptime_percentage for s in states) / total) if total > 0 else 100.0

        payload = {
            "text": "📊 SENTINEL DAILY SUMMARY",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "📊 SENTINEL DAILY SUMMARY"},
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Monitored:*\n{total}"},
                        {"type": "mrkdwn", "text": f"*Healthy:*\n{healthy}"},
                        {"type": "mrkdwn", "text": f"*Average Uptime:*\n{avg_uptime:.2f}%"},
                    ],
                },
            ],
        }
        return await self.send_message(payload)


class AlertDispatcher:
    """Coordinates notifications across all configured channels."""

    def __init__(
        self,
        telegram_cfg: Any,
        webhook_cfg: Any,
        discord_cfg: Any = None,
        slack_cfg: Any = None,
    ) -> None:
        self.telegram = TelegramNotifier(telegram_cfg)
        self.webhook = WebhookNotifier(webhook_cfg)
        self.discord = DiscordNotifier(discord_cfg)
        self.slack = SlackNotifier(slack_cfg)

    @property
    def is_configured(self) -> bool:
        return (
            self.telegram.config.is_configured
            or self.webhook.config.is_configured
            or self.discord.config.is_configured
            or self.slack.config.is_configured
        )

    async def send_outage_alert(
        self,
        state: TargetState,
        debounce_threshold: int,
        timestamp: datetime | None = None,
    ) -> bool:
        ts = timestamp or datetime.now(timezone.utc)
        results = await asyncio.gather(
            self.telegram.send_outage_alert(state, debounce_threshold, ts),
            self.webhook.send_webhook({
                "event": "outage",
                "target": state.name,
                "url": state.url,
                "status_code": state.last_status_code,
                "status_phrase": state.last_status_phrase,
                "latency_ms": state.last_latency_ms,
                "error_reason": state.last_error_reason,
                "consecutive_failures": state.consecutive_failures,
                "timestamp": ts.isoformat(),
            }),
            self.discord.send_outage_alert(state, debounce_threshold, ts),
            self.slack.send_outage_alert(state, debounce_threshold, ts),
            return_exceptions=True,
        )
        return any(r is True for r in results)

    async def send_recovery_alert(
        self,
        state: TargetState,
        timestamp: datetime | None = None,
    ) -> bool:
        ts = timestamp or datetime.now(timezone.utc)
        results = await asyncio.gather(
            self.telegram.send_recovery_alert(state, ts),
            self.webhook.send_webhook({
                "event": "recovery",
                "target": state.name,
                "url": state.url,
                "status_code": state.last_status_code,
                "latency_ms": state.last_latency_ms,
                "downtime_seconds": state.previous_downtime_seconds,
                "downtime_duration": format_duration(state.previous_downtime_seconds),
                "timestamp": ts.isoformat(),
            }),
            self.discord.send_recovery_alert(state, ts),
            self.slack.send_recovery_alert(state, ts),
            return_exceptions=True,
        )
        return any(r is True for r in results)

    async def send_test_alert(self) -> bool:
        results = await asyncio.gather(
            self.telegram.send_test_alert(),
            self.webhook.send_webhook({
                "event": "test",
                "message": "Sentinel alert delivery verified",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
            self.discord.send_test_alert(),
            self.slack.send_test_alert(),
            return_exceptions=True,
        )
        return any(r is True for r in results)

    async def send_daily_summary(
        self,
        states: list[TargetState],
        timestamp: datetime | None = None,
    ) -> bool:
        ts = timestamp or datetime.now(timezone.utc)
        results = await asyncio.gather(
            self.telegram.send_daily_summary(states, ts),
            self.webhook.send_webhook({
                "event": "daily_summary",
                "total_targets": len(states),
                "healthy_targets": sum(1 for s in states if s.status.value == "UP"),
                "targets": [
                    {
                        "name": s.name,
                        "url": s.url,
                        "status": s.status.value,
                        "uptime_percentage": s.uptime_percentage,
                        "average_latency_ms": s.average_latency_ms,
                    }
                    for s in states
                ],
                "timestamp": ts.isoformat(),
            }),
            self.discord.send_daily_summary(states, ts),
            self.slack.send_daily_summary(states, ts),
            return_exceptions=True,
        )
        return any(r is True for r in results)
