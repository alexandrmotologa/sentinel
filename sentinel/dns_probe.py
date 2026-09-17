"""Asynchronous DNS resolution probe and assertion validator."""

from __future__ import annotations

import asyncio
import socket
import struct
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sentinel.evaluator import BaseProbe, CheckResult

if TYPE_CHECKING:
    from sentinel.config import DNSTargetConfig


def _decode_dns_name(data: bytes, offset: int) -> tuple[str, int]:
    """Decode domain name from a DNS wire packet supporting label pointers."""
    labels: list[str] = []
    jumped = False
    original_offset = offset

    while offset < len(data):
        length = data[offset]
        if length == 0:
            offset += 1
            break
        if (length & 0xC0) == 0xC0:
            pointer = struct.unpack(">H", data[offset : offset + 2])[0] & 0x3FFF
            if not jumped:
                original_offset = offset + 2
                jumped = True
            offset = pointer
            continue
        offset += 1
        labels.append(data[offset : offset + length].decode("ascii", errors="replace"))
        offset += length

    return ".".join(labels), (original_offset if jumped else offset)


def _query_dns_packet(host: str, qtype: int, server: str = "1.1.1.1", timeout: float = 3.0) -> list[str]:
    """Send a lightweight UDP DNS query (RFC 1035) and parse record strings."""
    packet = struct.pack(">HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0)
    for part in host.strip(".").split("."):
        encoded = part.encode("ascii")
        packet += struct.pack("B", len(encoded)) + encoded
    packet += struct.pack(">BHH", 0, qtype, 1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(packet, (server, 53))
        resp_data, _ = sock.recvfrom(2048)
    finally:
        sock.close()

    if len(resp_data) < 12:
        return []

    _, _, qdcount, ancount, _, _ = struct.unpack(">HHHHHH", resp_data[:12])
    offset = 12

    # Skip question section
    for _ in range(qdcount):
        _, offset = _decode_dns_name(resp_data, offset)
        offset += 4  # skip qtype and qclass

    results: list[str] = []
    for _ in range(ancount):
        if offset >= len(resp_data):
            break
        _, offset = _decode_dns_name(resp_data, offset)
        if offset + 10 > len(resp_data):
            break
        rtype, _, _, rdlength = struct.unpack(">HHIH", resp_data[offset : offset + 10])
        offset += 10
        rdata = resp_data[offset : offset + rdlength]

        if rtype == 15 and len(rdata) > 2:  # MX
            preference = struct.unpack(">H", rdata[:2])[0]
            exchange, _ = _decode_dns_name(resp_data, offset + 2)
            results.append(f"{preference} {exchange}")
        elif rtype == 16 and len(rdata) > 0:  # TXT
            txt_len = rdata[0]
            txt_content = rdata[1 : 1 + txt_len].decode("utf-8", errors="replace")
            results.append(txt_content)
        elif rtype == 5:  # CNAME
            cname, _ = _decode_dns_name(resp_data, offset)
            results.append(cname)

        offset += rdlength

    return results


class DnsProbe(BaseProbe):
    """Health probe evaluating DNS name resolution, latency, and assertion rules."""

    def __init__(self, target: DNSTargetConfig) -> None:
        self.target = target

    async def check(self) -> CheckResult:
        """Execute asynchronous DNS query and validate configured expectations."""
        timeout = self.target.timeout or 5.0
        expect = self.target.expect
        start_time = time.perf_counter()
        loop = asyncio.get_running_loop()

        resolved_ips: list[str] = []
        resolved_cname: str | None = None
        records: list[str] = []

        try:
            record_type = self.target.record_type.upper()

            if record_type == "A":
                addr_info = await asyncio.wait_for(
                    loop.getaddrinfo(
                        self.target.host,
                        None,
                        family=socket.AF_INET,
                        type=socket.SOCK_STREAM,
                    ),
                    timeout=timeout,
                )
                for item in addr_info:
                    ip = item[4][0]
                    if ip not in resolved_ips:
                        resolved_ips.append(ip)

            elif record_type == "AAAA":
                addr_info = await asyncio.wait_for(
                    loop.getaddrinfo(
                        self.target.host,
                        None,
                        family=socket.AF_INET6,
                        type=socket.SOCK_STREAM,
                    ),
                    timeout=timeout,
                )
                for item in addr_info:
                    ip = item[4][0]
                    if ip not in resolved_ips:
                        resolved_ips.append(ip)

            elif record_type == "CNAME":
                addr_info = await asyncio.wait_for(
                    loop.getaddrinfo(
                        self.target.host,
                        None,
                        flags=socket.AI_CANONNAME,
                    ),
                    timeout=timeout,
                )
                for item in addr_info:
                    cname = item[3]
                    if cname and not resolved_cname:
                        resolved_cname = cname
                    ip = item[4][0]
                    if ip not in resolved_ips:
                        resolved_ips.append(ip)

            elif record_type in ("MX", "TXT"):
                qtype = 15 if record_type == "MX" else 16
                records = await asyncio.wait_for(
                    loop.run_in_executor(None, _query_dns_packet, self.target.host, qtype, "1.1.1.1", timeout),
                    timeout=timeout,
                )
                resolved_ips = list(records)

            else:
                addr_info = await asyncio.wait_for(
                    loop.getaddrinfo(self.target.host, None),
                    timeout=timeout,
                )
                for item in addr_info:
                    ip = item[4][0]
                    if ip not in resolved_ips:
                        resolved_ips.append(ip)

            latency_ms = (time.perf_counter() - start_time) * 1000.0

        except TimeoutError:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return CheckResult(
                passed=False,
                status_code=None,
                status_phrase="Timeout",
                latency_ms=latency_ms,
                error_reason=f"DNS query timed out after {timeout:.1f}s",
                resolved_ips=[],
                checked_at=datetime.now(UTC),
            )
        except socket.gaierror as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return CheckResult(
                passed=False,
                status_code=None,
                status_phrase="Resolution Failed",
                latency_ms=latency_ms,
                error_reason=f"DNS resolution failed: {exc}",
                resolved_ips=[],
                checked_at=datetime.now(UTC),
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return CheckResult(
                passed=False,
                status_code=None,
                status_phrase="DNS Error",
                latency_ms=latency_ms,
                error_reason=str(exc),
                resolved_ips=[],
                checked_at=datetime.now(UTC),
            )

        # Assertion: Check maximum allowable latency
        if expect.max_latency_ms is not None and latency_ms > expect.max_latency_ms:
            return CheckResult(
                passed=False,
                status_code=None,
                status_phrase="High Latency",
                latency_ms=latency_ms,
                error_reason=(
                    f"DNS lookup latency {latency_ms:.0f} ms exceeded "
                    f"limit {expect.max_latency_ms:.0f} ms"
                ),
                resolved_ips=resolved_ips,
                checked_at=datetime.now(UTC),
            )

        # Assertion: Check expected IP addresses
        if expect.expected_ips:
            missing = [ip for ip in expect.expected_ips if ip not in resolved_ips]
            if missing:
                return CheckResult(
                    passed=False,
                    status_code=None,
                    status_phrase="IP Mismatch",
                    latency_ms=latency_ms,
                    error_reason=(
                        f"Expected IP(s) {missing} not found in resolved IPs: {resolved_ips}"
                    ),
                    resolved_ips=resolved_ips,
                    checked_at=datetime.now(UTC),
                )

        # Assertion: Check expected CNAME
        if expect.expected_cname is not None:
            cname_val = resolved_cname or (records[0] if records else "")
            if not cname_val or expect.expected_cname.lower() not in cname_val.lower():
                return CheckResult(
                    passed=False,
                    status_code=None,
                    status_phrase="CNAME Mismatch",
                    latency_ms=latency_ms,
                    error_reason=(
                        f"Expected CNAME '{expect.expected_cname}', got '{cname_val}'"
                    ),
                    resolved_ips=resolved_ips,
                    checked_at=datetime.now(UTC),
                )

        return CheckResult(
            passed=True,
            status_code=None,
            status_phrase="Resolved",
            latency_ms=latency_ms,
            resolved_ips=resolved_ips,
            checked_at=datetime.now(UTC),
        )
