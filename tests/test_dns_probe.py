"""Unit tests for asynchronous DNS resolution probe and assertions."""

from __future__ import annotations

import asyncio
import socket
from unittest.mock import AsyncMock, patch

import pytest

from sentinel.config import DNSExpectConfig, DNSTargetConfig
from sentinel.dns_probe import DnsProbe
from sentinel.evaluator import evaluate_dns_target


@pytest.mark.asyncio
async def test_dns_probe_a_record_success():
    """Verify standard A record resolution returns expected IPs and latency."""
    target = DNSTargetConfig(
        name="Cloudflare DNS",
        host="one.one.one.one",
        record_type="A",
        expect=DNSExpectConfig(expected_ips=["1.1.1.1"]),
    )

    mock_addrinfo = [
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("1.1.1.1", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("1.0.0.1", 0)),
    ]

    with patch.object(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=mock_addrinfo)):
        probe = DnsProbe(target)
        result = await probe.check()

        assert result.passed is True
        assert result.status_phrase == "Resolved"
        assert result.latency_ms >= 0.0
        assert "1.1.1.1" in result.resolved_ips
        assert "1.0.0.1" in result.resolved_ips
        assert result.error_reason is None


@pytest.mark.asyncio
async def test_dns_probe_aaaa_record_success():
    """Verify AAAA record resolution resolves IPv6 address cleanly."""
    target = DNSTargetConfig(
        name="IPv6 Target",
        host="ipv6.example.com",
        record_type="AAAA",
    )

    mock_addrinfo = [
        (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2606:4700:4700::1111", 0, 0, 0)),
    ]

    with patch.object(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=mock_addrinfo)):
        probe = DnsProbe(target)
        result = await probe.check()

        assert result.passed is True
        assert result.status_phrase == "Resolved"
        assert "2606:4700:4700::1111" in result.resolved_ips


@pytest.mark.asyncio
async def test_dns_probe_expected_ip_mismatch():
    """Verify failure when expected IP is absent from resolved address set."""
    target = DNSTargetConfig(
        name="Google DNS",
        host="dns.google",
        record_type="A",
        expect=DNSExpectConfig(expected_ips=["9.9.9.9"]),
    )

    mock_addrinfo = [
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.4.4", 0)),
    ]

    with patch.object(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=mock_addrinfo)):
        probe = DnsProbe(target)
        result = await probe.check()

        assert result.passed is False
        assert result.status_phrase == "IP Mismatch"
        assert "9.9.9.9" in result.error_reason
        assert "8.8.8.8" in result.resolved_ips


@pytest.mark.asyncio
async def test_dns_probe_cname_match_and_mismatch():
    """Verify CNAME assertion checks against canonical name."""
    target_ok = DNSTargetConfig(
        name="CNAME Check",
        host="cdn.example.com",
        record_type="CNAME",
        expect=DNSExpectConfig(expected_cname="lb.cloudflare.com"),
    )

    mock_addrinfo_cname = [
        (socket.AF_INET, socket.SOCK_STREAM, 0, "lb.cloudflare.com", ("104.16.1.1", 0)),
    ]

    with patch.object(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=mock_addrinfo_cname)):
        probe_ok = DnsProbe(target_ok)
        result_ok = await probe_ok.check()
        assert result_ok.passed is True
        assert result_ok.status_phrase == "Resolved"

    # Mismatch expectation
    target_fail = DNSTargetConfig(
        name="CNAME Check Fail",
        host="cdn.example.com",
        record_type="CNAME",
        expect=DNSExpectConfig(expected_cname="aws.amazon.com"),
    )
    with patch.object(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=mock_addrinfo_cname)):
        probe_fail = DnsProbe(target_fail)
        result_fail = await probe_fail.check()
        assert result_fail.passed is False
        assert result_fail.status_phrase == "CNAME Mismatch"
        assert "aws.amazon.com" in result_fail.error_reason


@pytest.mark.asyncio
async def test_dns_probe_max_latency_exceeded():
    """Verify probe fails when DNS lookup latency breaches configured max."""
    target = DNSTargetConfig(
        name="Latency Test",
        host="slow.example.com",
        expect=DNSExpectConfig(max_latency_ms=10.0),
    )

    async def slow_getaddrinfo(*args, **kwargs):
        await asyncio.sleep(0.05)  # 50ms > 10ms
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("1.2.3.4", 0))]

    with patch.object(asyncio.get_running_loop(), "getaddrinfo", slow_getaddrinfo):
        probe = DnsProbe(target)
        result = await probe.check()

        assert result.passed is False
        assert result.status_phrase == "High Latency"
        assert "exceeded limit 10 ms" in result.error_reason


@pytest.mark.asyncio
async def test_dns_probe_timeout():
    """Verify timeout triggers graceful failure with Timeout status phrase."""
    target = DNSTargetConfig(
        name="Timeout Domain",
        host="timeout.example.com",
        timeout=0.5,
    )

    with patch.object(
        asyncio.get_running_loop(),
        "getaddrinfo",
        AsyncMock(side_effect=TimeoutError()),
    ):
        probe = DnsProbe(target)
        result = await probe.check()

        assert result.passed is False
        assert result.status_phrase == "Timeout"
        assert "timed out" in result.error_reason


@pytest.mark.asyncio
async def test_dns_probe_gaierror():
    """Verify socket.gaierror returns Resolution Failed."""
    target = DNSTargetConfig(
        name="NXDOMAIN Target",
        host="nonexistent.invalid.domain",
    )

    with patch.object(
        asyncio.get_running_loop(),
        "getaddrinfo",
        AsyncMock(side_effect=socket.gaierror(socket.EAI_NONAME, "Name or service not known")),
    ):
        probe = DnsProbe(target)
        result = await probe.check()

        assert result.passed is False
        assert result.status_phrase == "Resolution Failed"
        assert "DNS resolution failed" in result.error_reason


@pytest.mark.asyncio
async def test_evaluate_dns_target_facade():
    """Verify evaluate_dns_target facade delegates cleanly to DnsProbe."""
    target = DNSTargetConfig(name="Facade Test", host="one.one.one.one")
    mock_addrinfo = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("1.1.1.1", 0))]

    with patch.object(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=mock_addrinfo)):
        res = await evaluate_dns_target(target)
        assert res.passed is True
        assert res.status_phrase == "Resolved"
