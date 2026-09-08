"""Unit tests for health evaluation rules and HTTP assertions."""

import json
import pytest
import httpx

from sentinel.config import ExpectConfig, TargetConfig
from sentinel.evaluator import (
    CheckResult,
    _check_status_code,
    _match_json_structure,
    evaluate_target,
)


def test_status_code_checks():
    # Exact int
    ok, err = _check_status_code(200, 200)
    assert ok and err is None

    ok, err = _check_status_code(200, 404)
    assert not ok and "Expected status 200, got 404" in err

    # List of ints
    ok, err = _check_status_code([200, 201, 204], 201)
    assert ok and err is None

    ok, err = _check_status_code([200, 201], 500)
    assert not ok and "Expected status in [200, 201], got 500" in err

    # Range string
    ok, err = _check_status_code("200-299", 204)
    assert ok and err is None

    ok, err = _check_status_code("200-299", 301)
    assert not ok and "Expected status in range 200-299, got 301" in err


def test_json_matching():
    actual = {
        "status": "ok",
        "service": {
            "name": "payments",
            "ready": True,
        },
        "metrics": {"requests": 100},
    }

    # Match flat keys
    ok, err = _match_json_structure({"status": "ok"}, actual)
    assert ok and err is None

    # Match nested dict
    ok, err = _match_json_structure(
        {"service": {"name": "payments", "ready": True}}, actual
    )
    assert ok and err is None

    # Match dot-notation key
    ok, err = _match_json_structure({"service.ready": True}, actual)
    assert ok and err is None

    # Mismatch value
    ok, err = _match_json_structure({"status": "degraded"}, actual)
    assert not ok and "Expected JSON status = 'degraded', got 'ok'" in err

    # Missing key
    ok, err = _match_json_structure({"nonexistent": 1}, actual)
    assert not ok and "missing from response" in err


@pytest.mark.asyncio
async def test_evaluate_target_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={"status": "ok", "db": "healthy"},
            text='{"status": "ok", "db": "healthy"}',
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        target = TargetConfig(
            name="API Test",
            url="http://mock.local/health",
            expect=ExpectConfig(
                status_code=200,
                contains_text="healthy",
                json={"status": "ok"},
            ),
        )
        result = await evaluate_target(target, client)
        assert result.passed
        assert result.status_code == 200
        assert result.error_reason is None


@pytest.mark.asyncio
async def test_evaluate_target_status_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=503, text="Service Unavailable")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        target = TargetConfig(
            name="Failing API",
            url="http://mock.local/health",
            expect=ExpectConfig(status_code=200),
        )
        result = await evaluate_target(target, client)
        assert not result.passed
        assert result.status_code == 503
        assert "Expected status 200, got 503" in result.error_reason


@pytest.mark.asyncio
async def test_evaluate_target_regex_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, text="System: Maintenance mode active")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        target = TargetConfig(
            name="Regex Check",
            url="http://mock.local/status",
            expect=ExpectConfig(regex=r"System:\s+Ready"),
        )
        result = await evaluate_target(target, client)
        assert not result.passed
        assert "failed to match regex" in result.error_reason


@pytest.mark.asyncio
async def test_evaluate_target_latency_exceeded():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, text="OK")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        # Expect max latency 0.0001 ms (will certainly be exceeded)
        target = TargetConfig(
            name="Slow API",
            url="http://mock.local/fast",
            expect=ExpectConfig(max_latency_ms=0.0001),
        )
        result = await evaluate_target(target, client)
        assert not result.passed
        assert "exceeded limit" in result.error_reason


@pytest.mark.asyncio
async def test_evaluate_target_ssl_expiry_warning(monkeypatch):
    from sentinel import evaluator

    async def mock_get_ssl_days_left(url: str, timeout: float = 5.0) -> int:
        return 3  # expires in 3 days

    monkeypatch.setattr(evaluator, "get_ssl_days_left", mock_get_ssl_days_left)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, text="OK")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        target = TargetConfig(
            name="Expiring Cert",
            url="https://secure.example.com/api",
            expect=ExpectConfig(ssl_check=True, ssl_warn_days=7),
        )
        result = await evaluate_target(target, client)
        assert not result.passed
        assert "SSL certificate expires in 3 days" in result.error_reason
        assert result.ssl_days_left == 3


@pytest.mark.asyncio
async def test_evaluate_target_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timed out")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        target = TargetConfig(
            name="Timeout Check",
            url="http://mock.local/slow",
            timeout=1.0,
        )
        result = await evaluate_target(target, client)
        assert not result.passed
        assert result.status_code is None
        assert "timed out" in result.error_reason.lower()
