"""Unit tests for TCP socket connectivity evaluations."""

from __future__ import annotations

import asyncio
import pytest

from sentinel.config import TCPTargetConfig
from sentinel.evaluator import evaluate_tcp_target


@pytest.mark.asyncio
async def test_evaluate_tcp_target_success():
    # Start a mock TCP server on localhost on a free port
    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, host="127.0.0.1", port=0)
    assigned_port = server.sockets[0].getsockname()[1]

    try:
        target = TCPTargetConfig(
            name="local-tcp-service",
            host="127.0.0.1",
            port=assigned_port,
            timeout=2.0,
        )
        result = await evaluate_tcp_target(target)
        assert result.passed is True
        assert result.latency_ms > 0
        assert result.error_reason is None
        assert result.status_phrase == "Connected"
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_evaluate_tcp_target_connection_refused():
    # Choose a port that is unlikely to be listening (e.g. 59999)
    target = TCPTargetConfig(
        name="closed-port",
        host="127.0.0.1",
        port=59999,
        timeout=1.0,
    )
    result = await evaluate_tcp_target(target)
    assert result.passed is False
    assert result.status_phrase in ("Connection Refused", "Timeout", "Connection Failed")
    assert len(result.error_reason) > 0


@pytest.mark.asyncio
async def test_evaluate_tcp_target_timeout(monkeypatch):
    async def mock_open_connection(host, port):
        await asyncio.sleep(10.0)
        return None, None

    monkeypatch.setattr(asyncio, "open_connection", mock_open_connection)

    target = TCPTargetConfig(
        name="hung-service",
        host="127.0.0.1",
        port=9999,
        timeout=0.05,
    )
    result = await evaluate_tcp_target(target)
    assert result.passed is False
    assert result.status_phrase == "Timeout"
    assert result.error_reason is not None
    assert "timed out" in result.error_reason.lower()
