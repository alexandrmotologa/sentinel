from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
import pytest
import httpx

from sentinel.config import ExpectConfig, TargetConfig, TCPTargetConfig
from sentinel.engine import HeartbeatService, TargetWorker
from sentinel.evaluator import (
    BaseProbe,
    CheckResult,
    HttpAssertionPipeline,
    HttpProbe,
    JsonAssertion,
    LatencyAssertion,
    RegexAssertion,
    StatusCodeAssertion,
    TcpProbe,
    TextContentAssertion,
)
from sentinel.notifier import AlertDispatcher, BaseNotifier
from sentinel.server import HealthzExporter, HttpServerResponse, PrometheusExporter
from sentinel.state import TargetState, TargetStatus


class DummyNotifier(BaseNotifier):
    """Test notifier implementation of BaseNotifier."""

    def __init__(self, name: str = "dummy") -> None:
        self.name = name
        self.outages: list[str] = []
        self.recoveries: list[str] = []
        self.test_alerts: int = 0
        self.summaries: int = 0

    @property
    def is_configured(self) -> bool:
        return True

    async def send_outage_alert(
        self, state: TargetState, debounce_threshold: int, timestamp: datetime | None = None
    ) -> bool:
        self.outages.append(state.name)
        return True

    async def send_recovery_alert(self, state: TargetState, timestamp: datetime | None = None) -> bool:
        self.recoveries.append(state.name)
        return True

    async def send_test_alert(self) -> bool:
        self.test_alerts += 1
        return True

    async def send_daily_summary(
        self, states: list[TargetState], timestamp: datetime | None = None
    ) -> bool:
        self.summaries += 1
        return True


@pytest.mark.asyncio
async def test_assertion_strategies():
    """Verify individual Strategy implementations in isolation."""
    # Status code assertion
    status_strategy = StatusCodeAssertion()
    expect_200 = ExpectConfig(status_code=200)
    resp_ok = httpx.Response(200)
    passed, reason, _ = await status_strategy.validate(resp_ok, 50.0, expect_200, "http://x", 5.0)
    assert passed
    assert reason is None

    resp_fail = httpx.Response(404)
    passed, reason, _ = await status_strategy.validate(resp_fail, 50.0, expect_200, "http://x", 5.0)
    assert not passed
    assert "Expected status 200, got 404" in reason

    # Latency assertion
    latency_strategy = LatencyAssertion()
    expect_lat = ExpectConfig(max_latency_ms=100.0)
    passed, reason, _ = await latency_strategy.validate(resp_ok, 50.0, expect_lat, "http://x", 5.0)
    assert passed

    passed, reason, _ = await latency_strategy.validate(resp_ok, 150.0, expect_lat, "http://x", 5.0)
    assert not passed
    assert "exceeded limit 100 ms" in reason

    # Text assertion
    text_strategy = TextContentAssertion()
    expect_text = ExpectConfig(contains_text="UPTIME")
    resp_text_ok = httpx.Response(200, text="ALL UPTIME SYSTEMS")
    passed, _, _ = await text_strategy.validate(resp_text_ok, 10.0, expect_text, "http://x", 5.0)
    assert passed

    resp_text_fail = httpx.Response(200, text="DOWNTIME")
    passed, _, _ = await text_strategy.validate(resp_text_fail, 10.0, expect_text, "http://x", 5.0)
    assert not passed

    # Regex assertion
    regex_strategy = RegexAssertion()
    expect_regex = ExpectConfig(regex_match=r"v\d+\.\d+")
    resp_re_ok = httpx.Response(200, text="Sentinel v1.2")
    passed, _, _ = await regex_strategy.validate(resp_re_ok, 10.0, expect_regex, "http://x", 5.0)
    assert passed

    # Json assertion
    json_strategy = JsonAssertion()
    expect_json = ExpectConfig(json_match={"data.status": "active"})
    resp_json_ok = httpx.Response(200, json={"data": {"status": "active"}})
    passed, _, _ = await json_strategy.validate(resp_json_ok, 10.0, expect_json, "http://x", 5.0)
    assert passed


@pytest.mark.asyncio
async def test_http_assertion_pipeline():
    """Verify pipeline executes ordered strategies against response."""
    expect = ExpectConfig(
        status_code=200,
        max_latency_ms=300.0,
        contains_text="created",
    )
    pipeline = HttpAssertionPipeline()

    resp_ok = httpx.Response(200, text="created successfully")
    passed, reason, _ = await pipeline.run(resp_ok, 100.0, expect, "http://test", 5.0)
    assert passed
    assert reason is None

    passed_fail, reason_fail, _ = await pipeline.run(resp_ok, 450.0, expect, "http://test", 5.0)
    assert not passed_fail
    assert "exceeded limit 300 ms" in reason_fail


@pytest.mark.asyncio
async def test_polymorphic_probe_hierarchy():
    """Verify BaseProbe polymorphic subclasses."""
    target = TargetConfig(name="test-http", url="https://example.com")
    transport = httpx.MockTransport(lambda req: httpx.Response(200, text="OK"))
    async with httpx.AsyncClient(transport=transport) as client:
        http_probe = HttpProbe(target, client)
        assert isinstance(http_probe, BaseProbe)
        res = await http_probe.check()
        assert res.passed
        assert res.status_code == 200

    tcp_target = TCPTargetConfig(name="test-tcp", host="127.0.0.1", port=9999)
    tcp_probe = TcpProbe(tcp_target)
    assert isinstance(tcp_probe, BaseProbe)


def test_heartbeat_service(tmp_path: Path):
    """Verify HeartbeatService file operations and status checks."""
    hb_file = tmp_path / "custom.heartbeat"
    svc = HeartbeatService(path=hb_file)

    assert not svc.is_healthy()
    svc.write()
    assert hb_file.exists()
    assert svc.is_healthy(max_age_seconds=10.0)


@pytest.mark.asyncio
async def test_target_worker_execution(tmp_path: Path):
    """Verify TargetWorker executes probe and manages notifications cleanly."""
    class MockProbe(BaseProbe):
        def __init__(self, target_name: str, passed: bool) -> None:
            self.target_name = target_name
            self.should_pass = passed

        async def check(self) -> CheckResult:
            return CheckResult(
                passed=self.should_pass,
                status_code=200 if self.should_pass else 500,
                latency_ms=42.0,
                error_reason=None if self.should_pass else "Failure",
            )

    probe = MockProbe("mock-api", passed=False)
    state = TargetState(name="mock-api", url="https://mock.local")
    stop_event = asyncio.Event()
    hb = HeartbeatService(tmp_path / "worker.hb")

    dispatcher = AlertDispatcher()
    dummy = DummyNotifier()
    dispatcher.register(dummy)

    worker = TargetWorker(
        name="mock-api",
        probe=probe,
        state=state,
        interval=0.01,
        debounce_threshold=1,
        notifier=dispatcher,
        stop_event=stop_event,
        heartbeat=hb,
    )

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    stop_event.set()
    await task
    await asyncio.sleep(0.05)

    assert len(dummy.outages) >= 1
    assert "mock-api" in dummy.outages


def test_exporters():
    """Verify Prometheus and Healthz exporter classes."""
    states = {
        "api": TargetState(name="api", url="https://api.test", status=TargetStatus.UP),
        "db": TargetState(name="db", url="tcp://127.0.0.1:5432", status=TargetStatus.DOWN),
    }

    prom = PrometheusExporter.format_metrics(states)
    assert "sentinel_target_up" in prom
    assert 'target="api"} 1' in prom
    assert 'target="db"} 0' in prom

    health = HealthzExporter.format_payload(states)
    assert health["status"] == "degraded"
    assert health["total_targets"] == 2
    assert health["healthy_targets"] == 1

    resp = HttpServerResponse(200, "OK", "text/plain", b"Hello")
    encoded = resp.to_bytes()
    assert b"HTTP/1.1 200 OK" in encoded
    assert b"Content-Type: text/plain" in encoded
    assert b"Hello" in encoded
