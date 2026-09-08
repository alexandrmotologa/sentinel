"""Unit tests for Telegram notification formatting and delivery."""

import json
import pytest
import httpx
from datetime import datetime, timezone

from sentinel.config import TelegramConfig
from sentinel.notifier import TelegramNotifier
from sentinel.state import TargetState


@pytest.mark.asyncio
async def test_notifier_unconfigured():
    notifier = TelegramNotifier(TelegramConfig(enabled=False))
    sent = await notifier.send_message("Hello")
    assert not sent


@pytest.mark.asyncio
async def test_outage_alert_formatting():
    captured_payload = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.content.decode("utf-8"))
        return httpx.Response(status_code=200, json={"ok": True})

    transport = httpx.MockTransport(handler)

    # Patch AsyncClient in notifier to use mock transport
    config = TelegramConfig(bot_token="test_token", chat_id="12345", enabled=True)
    notifier = TelegramNotifier(config)

    state = TargetState(
        name="Production <API> & Service",
        url="https://api.example.com/health?query=1&foo=2",
        last_status_code=503,
        last_status_phrase="Service Unavailable",
        last_latency_ms=2410.0,
        last_error_reason="Expected JSON status='ok', got 'error'",
        consecutive_failures=2,
    )

    test_time = datetime(2026, 9, 9, 0, 35, 12, tzinfo=timezone.utc)

    # Monkeypatch httpx.AsyncClient instantiation inside send_message
    orig_async_client = httpx.AsyncClient
    try:
        httpx.AsyncClient = lambda **kwargs: orig_async_client(transport=transport, **kwargs)
        sent = await notifier.send_outage_alert(state, debounce_threshold=2, timestamp=test_time)
    finally:
        httpx.AsyncClient = orig_async_client

    assert sent
    assert captured_payload is not None
    assert captured_payload["chat_id"] == "12345"
    assert captured_payload["parse_mode"] == "HTML"

    text = captured_payload["text"]
    assert "🚨 <b>SERVICE DOWN: Production &lt;API&gt; &amp; Service</b>" in text
    assert "https://api.example.com/health?query=1&amp;foo=2" in text
    assert "503 Service Unavailable" in text
    assert "2,410 ms" in text
    assert "2 / 2" in text
    assert "2026-09-09 00:35:12 UTC" in text


@pytest.mark.asyncio
async def test_recovery_alert_formatting():
    captured_payload = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.content.decode("utf-8"))
        return httpx.Response(status_code=200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    config = TelegramConfig(
        bot_token="test_token", chat_id="12345", send_silently=True, enabled=True
    )
    notifier = TelegramNotifier(config)

    state = TargetState(
        name="Production API",
        url="https://api.example.com/health",
        last_status_code=200,
        last_status_phrase="OK",
        last_latency_ms=185.0,
        previous_downtime_seconds=255.0,  # 4 minutes, 15 seconds
    )

    test_time = datetime(2026, 9, 9, 0, 39, 27, tzinfo=timezone.utc)

    orig_async_client = httpx.AsyncClient
    try:
        httpx.AsyncClient = lambda **kwargs: orig_async_client(transport=transport, **kwargs)
        sent = await notifier.send_recovery_alert(state, timestamp=test_time)
    finally:
        httpx.AsyncClient = orig_async_client

    assert sent
    assert captured_payload["disable_notification"] is True
    text = captured_payload["text"]
    assert "✅ <b>SERVICE RECOVERED: Production API</b>" in text
    assert "4 minutes, 15 seconds" in text
    assert "200 OK" in text
    assert "185 ms" in text
    assert "2026-09-09 00:39:27 UTC" in text


@pytest.mark.asyncio
async def test_notifier_retries_on_failure():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(status_code=502, text="Bad Gateway")
        return httpx.Response(status_code=200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    config = TelegramConfig(bot_token="test_token", chat_id="12345", enabled=True)
    notifier = TelegramNotifier(config)

    orig_async_client = httpx.AsyncClient
    try:
        httpx.AsyncClient = lambda **kwargs: orig_async_client(transport=transport, **kwargs)
        sent = await notifier.send_message("Test retry", max_retries=2)
    finally:
        httpx.AsyncClient = orig_async_client

    assert sent
    assert attempts == 2


@pytest.mark.asyncio
async def test_test_alert_formatting():
    captured_payload = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.content.decode("utf-8"))
        return httpx.Response(status_code=200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    config = TelegramConfig(bot_token="test_token", chat_id="12345", enabled=True)
    notifier = TelegramNotifier(config)

    orig_async_client = httpx.AsyncClient
    try:
        httpx.AsyncClient = lambda **kwargs: orig_async_client(transport=transport, **kwargs)
        sent = await notifier.send_test_alert()
    finally:
        httpx.AsyncClient = orig_async_client

    assert sent
    assert "SENTINEL TEST ALERT" in captured_payload["text"]


@pytest.mark.asyncio
async def test_daily_summary_formatting():
    captured_payload = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.content.decode("utf-8"))
        return httpx.Response(status_code=200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    config = TelegramConfig(bot_token="test_token", chat_id="12345", enabled=True)
    notifier = TelegramNotifier(config)

    s1 = TargetState(name="API 1", url="https://api1.com", total_checks=10, successful_checks=10)
    s1.status = s1.status.UP
    s2 = TargetState(name="API 2", url="https://api2.com", total_checks=10, successful_checks=5)
    s2.status = s2.status.DOWN

    orig_async_client = httpx.AsyncClient
    try:
        httpx.AsyncClient = lambda **kwargs: orig_async_client(transport=transport, **kwargs)
        sent = await notifier.send_daily_summary([s1, s2])
    finally:
        httpx.AsyncClient = orig_async_client

    assert sent
    text = captured_payload["text"]
    assert "SENTINEL DAILY SUMMARY" in text
    assert "Monitored Services:</b> 2" in text
    assert "Healthy Services:</b> 1" in text
    assert "75.00%" in text
    assert "API 1" in text
    assert "API 2" in text
