"""Unit tests for embedded Prometheus metrics and healthz server."""

from __future__ import annotations

import asyncio
import pytest
import httpx

from sentinel.evaluator import CheckResult
from sentinel.server import MetricsServer, generate_healthz_payload, generate_prometheus_metrics
from sentinel.state import TargetState, TargetStatus


def test_generate_prometheus_metrics():
    state1 = TargetState(name="api-prod", url="https://api.example.com")
    result1 = CheckResult(
        passed=True,
        status_code=200,
        status_phrase="OK",
        latency_ms=120.5,
    )
    state1.update(result1, debounce_threshold=2)

    state2 = TargetState(name="db-cache", url="tcp://127.0.0.1:6379")
    result2 = CheckResult(
        passed=False,
        status_code=None,
        status_phrase="Connection Refused",
        latency_ms=500.0,
        error_reason="Connection refused",
    )
    state2.update(result2, debounce_threshold=2)

    states = {"api-prod": state1, "db-cache": state2}
    metrics = generate_prometheus_metrics(states)

    assert '# HELP sentinel_target_up' in metrics
    assert '# TYPE sentinel_target_up gauge' in metrics
    assert 'sentinel_target_up{target="api-prod"} 1' in metrics
    assert 'sentinel_target_up{target="db-cache"} 0' in metrics
    assert 'sentinel_target_latency_seconds{target="api-prod"} 0.120500' in metrics
    assert 'sentinel_target_consecutive_failures{target="db-cache"} 1' in metrics
    assert 'sentinel_checks_total{target="api-prod"} 1' in metrics


def test_generate_healthz_payload():
    state1 = TargetState(name="api-prod", url="https://api.example.com")
    state1.update(
        CheckResult(
            passed=True,
            status_code=200,
            status_phrase="OK",
            latency_ms=50.0,
        ),
        debounce_threshold=2,
    )

    states = {"api-prod": state1}
    payload = generate_healthz_payload(states)

    assert payload["status"] == "healthy"
    assert payload["total_targets"] == 1
    assert payload["healthy_targets"] == 1
    assert "api-prod" in payload["targets"]
    assert payload["targets"]["api-prod"]["status"] == "UP"

    # Now simulate failure on second target
    state2 = TargetState(name="billing", url="https://pay.example.com")
    state2.update(
        CheckResult(
            passed=False,
            status_code=500,
            status_phrase="Internal Server Error",
            latency_ms=100.0,
            error_reason="Expected 200, got 500",
        ),
        debounce_threshold=1,
    )
    states["billing"] = state2
    degraded = generate_healthz_payload(states)
    assert degraded["status"] == "degraded"
    assert degraded["total_targets"] == 2
    assert degraded["healthy_targets"] == 1


@pytest.mark.asyncio
async def test_metrics_server_endpoints():
    state = TargetState(name="svc-1", url="https://svc1.example.com")
    state.status = TargetStatus.UP
    state.last_latency_ms = 45.0

    states = {"svc-1": state}
    server = MetricsServer(host="127.0.0.1", port=0, state_provider=lambda: states)
    await server.start()

    # Retrieve assigned port
    sockets = server.server.sockets
    assert sockets is not None and len(sockets) > 0
    assigned_port = sockets[0].getsockname()[1]

    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{assigned_port}") as client:
            resp_metrics = await client.get("/metrics")
            assert resp_metrics.status_code == 200
            assert "text/plain" in resp_metrics.headers["content-type"]
            assert 'sentinel_target_up{target="svc-1"} 1' in resp_metrics.text

            resp_healthz = await client.get("/healthz")
            assert resp_healthz.status_code == 200
            assert "application/json" in resp_healthz.headers["content-type"]
            data = resp_healthz.json()
            assert data["status"] == "healthy"

            resp_404 = await client.get("/unknown-path")
            assert resp_404.status_code == 404
    finally:
        await server.stop()
