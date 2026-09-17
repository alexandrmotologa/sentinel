"""Native cross-platform ICMP Ping probe."""

from __future__ import annotations

import asyncio
import logging
import platform
import re
import shutil
import time
from datetime import UTC, datetime

from sentinel.config import PingTargetConfig
from sentinel.evaluator import BaseProbe, CheckResult

logger = logging.getLogger("sentinel.ping_probe")

_LOSS_PATTERN = re.compile(r"(\d+(?:\.\d+)?)%\s*(?:packet\s+)?loss", re.IGNORECASE)
_RTT_NIX_PATTERN = re.compile(
    r"(?:rtt|round-trip)\s+min/avg/max/(?:mdev|stddev)\s*=\s*[\d\.]+/([\d\.]+)/",
    re.IGNORECASE,
)
_RTT_WIN_PATTERN = re.compile(r"Average\s*=\s*(\d+)ms", re.IGNORECASE)
_TIME_SAMPLE_PATTERN = re.compile(r"time[=<]([\d\.]+)ms", re.IGNORECASE)


def parse_ping_output(output: str, returncode: int, elapsed_ms: float) -> tuple[float, float, str | None]:
    """Parse ping CLI output into (latency_ms, packet_loss_percent, error_reason)."""
    # 1. Packet loss percentage
    loss_match = _LOSS_PATTERN.search(output)
    if loss_match:
        packet_loss = float(loss_match.group(1))
    elif returncode != 0:
        packet_loss = 100.0
    else:
        packet_loss = 0.0

    # 2. Round-trip latency
    latency_ms: float | None = None
    rtt_nix = _RTT_NIX_PATTERN.search(output)
    if rtt_nix:
        latency_ms = float(rtt_nix.group(1))
    else:
        rtt_win = _RTT_WIN_PATTERN.search(output)
        if rtt_win:
            latency_ms = float(rtt_win.group(1))
        else:
            time_sample = _TIME_SAMPLE_PATTERN.search(output)
            if time_sample:
                latency_ms = float(time_sample.group(1))

    if latency_ms is None:
        latency_ms = elapsed_ms if returncode == 0 else 0.0

    # 3. Error detection
    error_reason: str | None = None
    lower_out = output.lower()

    if packet_loss >= 100.0 or returncode != 0:
        if "destination host unreachable" in lower_out:
            error_reason = "Destination host unreachable"
        elif "request timed out" in lower_out:
            error_reason = "Request timed out"
        elif any(phrase in lower_out for phrase in ["could not find host", "name or service not known", "cannot resolve"]):
            error_reason = "Host resolution failed"
        else:
            error_reason = f"Host unreachable ({int(packet_loss)}% packet loss)"
    elif packet_loss > 0.0:
        error_reason = f"Packet loss detected ({int(packet_loss)}%)"

    return latency_ms, packet_loss, error_reason


class PingProbe(BaseProbe):
    """Asynchronous ICMP ping probe without root or raw socket requirements."""

    def __init__(self, target: PingTargetConfig, system: str | None = None) -> None:
        self.target = target
        self.system = (system or platform.system()).lower()

    def _build_command(self) -> list[str]:
        """Construct platform-specific ping command arguments."""
        host = self.target.host
        count = str(self.target.count)
        timeout_sec = self.target.timeout or 5.0

        if self.system == "windows":
            timeout_ms = str(int(timeout_sec * 1000))
            return ["ping", "-n", count, "-w", timeout_ms, host]
        elif self.system == "darwin":
            timeout_ms = str(int(timeout_sec * 1000))
            return ["ping", "-c", count, "-W", timeout_ms, host]
        else:
            # Linux and other Unix systems
            timeout_s = str(max(1, int(timeout_sec)))
            return ["ping", "-c", count, "-W", timeout_s, host]

    def _parse_output(
        self,
        output: str,
        exit_code: int = 0,
        elapsed_sec: float = 0.0,
    ) -> CheckResult:
        """Evaluate raw ping CLI output against target assertions."""
        elapsed_ms = elapsed_sec * 1000.0
        latency_ms, packet_loss, parse_error = parse_ping_output(output, exit_code, elapsed_ms)

        if (
            self.target.expect.max_packet_loss_percent is not None
            and packet_loss > self.target.expect.max_packet_loss_percent
        ):
            return CheckResult(
                passed=False,
                status_phrase=f"Packet Loss ({int(packet_loss)}%)",
                latency_ms=latency_ms,
                error_reason=f"Packet loss {packet_loss:.1f}% exceeded max allowed {self.target.expect.max_packet_loss_percent:.1f}%",
                checked_at=datetime.now(UTC),
            )

        if parse_error is not None:
            return CheckResult(
                passed=False,
                status_phrase="Unreachable",
                latency_ms=latency_ms,
                error_reason=parse_error,
                checked_at=datetime.now(UTC),
            )

        if (
            self.target.expect.max_latency_ms is not None
            and latency_ms > self.target.expect.max_latency_ms
        ):
            return CheckResult(
                passed=False,
                status_phrase="High Latency",
                latency_ms=latency_ms,
                error_reason=f"Average latency {latency_ms:.1f}ms exceeded max allowed {self.target.expect.max_latency_ms:.1f}ms",
                checked_at=datetime.now(UTC),
            )

        loss_str = f"{int(packet_loss)}% loss"
        return CheckResult(
            passed=True,
            status_phrase=f"Echo Reply ({loss_str}, {int(latency_ms)}ms)",
            latency_ms=latency_ms,
            error_reason=None,
            checked_at=datetime.now(UTC),
        )

    async def check(self) -> CheckResult:
        """Execute async subprocess ping and validate latency assertions."""
        timeout = self.target.timeout or 5.0
        cmd = self._build_command()

        ping_bin = shutil.which("ping")
        if not ping_bin and self.system != "windows":
            return CheckResult(
                passed=False,
                status_phrase="Ping Not Installed",
                latency_ms=0.0,
                error_reason="System ping executable not found in PATH",
                checked_at=datetime.now(UTC),
            )

        start_time = time.perf_counter()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, _ = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout + 2.0,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            output = stdout_bytes.decode("utf-8", errors="replace")
            returncode = proc.returncode if proc.returncode is not None else 1
        except TimeoutError:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            try:
                proc.kill()
            except Exception:
                pass
            return CheckResult(
                passed=False,
                status_phrase="Timeout",
                latency_ms=elapsed_ms,
                error_reason=f"Ping timed out after {timeout:.1f}s",
                checked_at=datetime.now(UTC),
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return CheckResult(
                passed=False,
                status_phrase="Subprocess Error",
                latency_ms=elapsed_ms,
                error_reason=str(exc),
                checked_at=datetime.now(UTC),
            )

        return self._parse_output(output, exit_code=returncode, elapsed_sec=elapsed_ms / 1000.0)


async def evaluate_ping_target(target: PingTargetConfig) -> CheckResult:
    """Convenience evaluator facade for immediate one-off ping probing."""
    probe = PingProbe(target)
    return await probe.check()
