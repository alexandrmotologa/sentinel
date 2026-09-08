"""Unit tests for Discord and Slack alert notifications."""

from __future__ import annotations

import json
import pytest
import httpx

from sentinel.config import DiscordConfig, SlackConfig
from sentinel.notifier import AlertDispatcher, DiscordNotifier, SlackNotifier
from sentinel.state import TargetState, TargetStatus


@pytest.mark.asyncio
async def test_discord_notifier_outage_and_recovery():
    captured_payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content.decode("utf-8"))
        captured_payloads.append(data)
        return httpx.Response(status_code=204)

    transport = httpx.MockTransport(handler)
    orig_async_client = httpx.AsyncClient
    httpx.AsyncClient = lambda **kwargs: orig_async_client(transport=transport, **kwargs)

    try:
        discord_config = DiscordConfig(
            webhook_url="https://discord.com/api/webhooks/123/abc",
            enabled=True,
        )
        notifier = DiscordNotifier(discord_config)
        state = TargetState(name="api-gateway", url="https://api.example.com")
        state.status = TargetStatus.DOWN
        state.last_error_reason = "HTTP 502 Bad Gateway"
        state.last_latency_ms = 432.1

        success = await notifier.send_outage_alert(state, debounce_threshold=3)
        assert success is True
        assert len(captured_payloads) == 1
        outage_data = captured_payloads[0]
        assert "embeds" in outage_data
        embed = outage_data["embeds"][0]
        assert "api-gateway" in embed["title"]
        assert embed["color"] == 15158332  # 0xE74C3C

        # Recovery alert
        state.status = TargetStatus.UP
        recovery_success = await notifier.send_recovery_alert(state)
        assert recovery_success is True
        assert len(captured_payloads) == 2
        rec_data = captured_payloads[1]
        rec_embed = rec_data["embeds"][0]
        assert "api-gateway" in rec_embed["title"]
        assert rec_embed["color"] == 3066993  # 0x2ECC71
    finally:
        httpx.AsyncClient = orig_async_client


@pytest.mark.asyncio
async def test_discord_test_alert():
    captured_payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content.decode("utf-8"))
        captured_payloads.append(data)
        return httpx.Response(status_code=204)

    transport = httpx.MockTransport(handler)
    orig_async_client = httpx.AsyncClient
    httpx.AsyncClient = lambda **kwargs: orig_async_client(transport=transport, **kwargs)

    try:
        discord_config = DiscordConfig(
            webhook_url="https://discord.com/api/webhooks/test",
            enabled=True,
        )
        notifier = DiscordNotifier(discord_config)
        success = await notifier.send_test_alert()
        assert success is True
        assert len(captured_payloads) == 1
        assert "SENTINEL TEST ALERT" in captured_payloads[0]["embeds"][0]["title"]
    finally:
        httpx.AsyncClient = orig_async_client


@pytest.mark.asyncio
async def test_slack_notifier_outage_and_recovery():
    captured_payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content.decode("utf-8"))
        captured_payloads.append(data)
        return httpx.Response(status_code=200, text="ok")

    transport = httpx.MockTransport(handler)
    orig_async_client = httpx.AsyncClient
    httpx.AsyncClient = lambda **kwargs: orig_async_client(transport=transport, **kwargs)

    try:
        slack_config = SlackConfig(
            webhook_url="https://hooks.slack.com/services/T00/B00/X00",
            enabled=True,
        )
        notifier = SlackNotifier(slack_config)
        state = TargetState(name="db-replica", url="tcp://10.0.0.5:5432")
        state.status = TargetStatus.DOWN
        state.last_error_reason = "Connection refused"

        success = await notifier.send_outage_alert(state, debounce_threshold=2)
        assert success is True
        assert len(captured_payloads) == 1
        outage_payload = captured_payloads[0]
        assert "blocks" in outage_payload
        header = outage_payload["blocks"][0]["text"]["text"]
        assert "SERVICE DOWN" in header

        # Recovery
        state.status = TargetStatus.UP
        recovery_success = await notifier.send_recovery_alert(state)
        assert recovery_success is True
        assert len(captured_payloads) == 2
        rec_payload = captured_payloads[1]
        rec_header = rec_payload["blocks"][0]["text"]["text"]
        assert "SERVICE RECOVERED" in rec_header
    finally:
        httpx.AsyncClient = orig_async_client


@pytest.mark.asyncio
async def test_alert_dispatcher_all_channels():
    requests_received = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_received.append(str(request.url))
        return httpx.Response(status_code=200, text="ok")

    transport = httpx.MockTransport(handler)
    orig_async_client = httpx.AsyncClient
    httpx.AsyncClient = lambda **kwargs: orig_async_client(transport=transport, **kwargs)

    try:
        discord_config = DiscordConfig(webhook_url="https://discord.com/hook", enabled=True)
        slack_config = SlackConfig(webhook_url="https://slack.com/hook", enabled=True)
        dispatcher = AlertDispatcher(
            telegram_cfg=None,
            webhook_cfg=None,
            discord_cfg=discord_config,
            slack_cfg=slack_config,
        )

        state = TargetState(name="multi-test", url="https://multi.example.com")
        state.status = TargetStatus.DOWN
        state.last_error_reason = "Timeout"

        await dispatcher.send_outage_alert(state, debounce_threshold=3)
        assert len(requests_received) == 2
        assert any("discord.com" in url for url in requests_received)
        assert any("slack.com" in url for url in requests_received)
    finally:
        httpx.AsyncClient = orig_async_client
