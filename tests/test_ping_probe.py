"""Tests for ICMP PingProbe cross-platform execution and output parsing."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from sentinel.config import PingExpectConfig, PingTargetConfig
from sentinel.evaluator import evaluate_ping_target
from sentinel.ping_probe import PingProbe


def test_ping_command_construction() -> None:
    target = PingTargetConfig(name="test-ping", host="1.1.1.1", count=3, timeout=2.0)
    probe_win = PingProbe(target, system="windows")
    assert probe_win._build_command() == ["ping", "-n", "3", "-w", "2000", "1.1.1.1"]

    probe_nix = PingProbe(target, system="linux")
    assert probe_nix._build_command() == ["ping", "-c", "3", "-W", "2", "1.1.1.1"]


def test_parse_windows_ping_output() -> None:
    target = PingTargetConfig(
        name="win-ping",
        host="8.8.8.8",
        expect=PingExpectConfig(max_latency_ms=50.0, max_packet_loss_percent=0.0),
    )
    probe = PingProbe(target, system="windows")

    windows_output = """
Pinging 8.8.8.8 with 32 bytes of data:
Reply from 8.8.8.8: bytes=32 time=14ms TTL=117
Reply from 8.8.8.8: bytes=32 time=15ms TTL=117
Reply from 8.8.8.8: bytes=32 time=13ms TTL=117

Ping statistics for 8.8.8.8:
    Packets: Sent = 3, Received = 3, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 13ms, Maximum = 15ms, Average = 14ms
"""
    result = probe._parse_output(windows_output, exit_code=0, elapsed_sec=0.05)
    assert result.passed is True
    assert result.latency_ms == 14.0
    assert result.status_phrase == "Echo Reply (0% loss, 14ms)"


def test_parse_linux_ping_output() -> None:
    target = PingTargetConfig(
        name="linux-ping",
        host="1.1.1.1",
        expect=PingExpectConfig(max_latency_ms=100.0, max_packet_loss_percent=0.0),
    )
    probe = PingProbe(target, system="linux")

    linux_output = """
PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
64 bytes from 1.1.1.1: icmp_seq=1 ttl=58 time=12.4 ms
64 bytes from 1.1.1.1: icmp_seq=2 ttl=58 time=11.9 ms

--- 1.1.1.1 ping statistics ---
2 packets transmitted, 2 received, 0% packet loss, time 1001ms
rtt min/avg/max/mdev = 11.912/12.156/12.400/0.244 ms
"""
    result = probe._parse_output(linux_output, exit_code=0, elapsed_sec=1.0)
    assert result.passed is True
    assert round(result.latency_ms, 1) == 12.2
    assert "0% loss" in result.status_phrase


def test_ping_max_latency_exceeded() -> None:
    target = PingTargetConfig(
        name="high-lat-ping",
        host="8.8.8.8",
        expect=PingExpectConfig(max_latency_ms=20.0),
    )
    probe = PingProbe(target, system="windows")

    windows_output = """
Packets: Sent = 3, Received = 3, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 45ms, Maximum = 55ms, Average = 50ms
"""
    result = probe._parse_output(windows_output, exit_code=0, elapsed_sec=0.1)
    assert result.passed is False
    assert "Average latency 50.0ms exceeded max allowed 20.0ms" in (result.error_reason or "")


def test_ping_packet_loss_failure() -> None:
    target = PingTargetConfig(
        name="lossy-ping",
        host="10.0.0.99",
        expect=PingExpectConfig(max_packet_loss_percent=10.0),
    )
    probe = PingProbe(target, system="windows")

    windows_output = """
Request timed out.
Request timed out.
Packets: Sent = 4, Received = 2, Lost = 2 (50% loss),
"""
    result = probe._parse_output(windows_output, exit_code=0, elapsed_sec=2.0)
    assert result.passed is False
    assert "Packet loss 50.0% exceeded max allowed 10.0%" in (result.error_reason or "")


@pytest.mark.asyncio
async def test_ping_probe_async_execution() -> None:
    target = PingTargetConfig(name="async-ping", host="127.0.0.1", count=1)
    probe = PingProbe(target)

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (
        b"Packets: Sent = 1, Received = 1, Lost = 0 (0% loss)\nAverage = 5ms",
        b"",
    )
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await probe.check()
        assert result.passed is True
        assert result.latency_ms == 5.0


@pytest.mark.asyncio
async def test_evaluate_ping_target_facade() -> None:
    target = PingTargetConfig(name="facade-ping", host="127.0.0.1", count=1)
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (
        b"Packets: Sent = 1, Received = 1, Lost = 0 (0% loss)\nAverage = 8ms",
        b"",
    )
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await evaluate_ping_target(target)
        assert result.passed is True
        assert result.latency_ms == 8.0
