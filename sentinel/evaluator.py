"""Health evaluation engine, polymorphic probes, and assertion pipeline."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
import socket
import ssl
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from sentinel.config import ExpectConfig, TargetConfig, TCPTargetConfig


@dataclass
class CheckResult:
    """Outcome of an endpoint health evaluation."""

    passed: bool
    status_code: int | None = None
    status_phrase: str = ""
    latency_ms: float = 0.0
    error_reason: str | None = None
    ssl_days_left: int | None = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def http_status_text(self) -> str:
        """Formatted representation of HTTP status code and reason phrase."""
        if self.status_code is not None:
            return f"{self.status_code} {self.status_phrase}".strip()
        return self.status_phrase


def create_async_client(**kwargs: Any) -> httpx.AsyncClient:
    """Create an httpx.AsyncClient with HTTP/2 enabled when available."""
    try:
        import h2  # noqa: F401
        has_http2 = True
    except ImportError:
        has_http2 = False

    kwargs.setdefault("http2", has_http2)
    return httpx.AsyncClient(**kwargs)


# ---------------------------------------------------------------------------
# Assertion Strategy Components
# ---------------------------------------------------------------------------

def _check_status_code(expected: Any, actual: int) -> tuple[bool, str | None]:
    """Validate actual status code against expected integer, list, or range string."""
    if expected is None:
        return True, None

    if isinstance(expected, int):
        if actual == expected:
            return True, None
        return False, f"Expected status {expected}, got {actual}"

    if isinstance(expected, list):
        int_codes = [int(c) for c in expected]
        if actual in int_codes:
            return True, None
        return False, f"Expected status in {int_codes}, got {actual}"

    if isinstance(expected, str):
        # Support ranges such as '200-299'
        if "-" in expected:
            parts = expected.split("-", 1)
            try:
                start = int(parts[0].strip())
                end = int(parts[1].strip())
                if start <= actual <= end:
                    return True, None
                return False, f"Expected status in range {start}-{end}, got {actual}"
            except ValueError:
                pass
        try:
            single = int(expected.strip())
            if actual == single:
                return True, None
            return False, f"Expected status {single}, got {actual}"
        except ValueError:
            pass

    return True, None


def _get_nested_json_value(data: Any, key_path: str) -> tuple[bool, Any]:
    """Retrieve a nested dictionary value using dot notation (e.g. 'service.status')."""
    parts = key_path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, None
    return True, current


def _match_json_structure(expected: Any, actual: Any, path: str = "") -> tuple[bool, str | None]:
    """Recursively match expected schema structure against parsed JSON response."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False, f"Expected JSON object at '{path or '$'}', got {type(actual).__name__}"
        for k, v in expected.items():
            subpath = f"{path}.{k}" if path else k
            if "." in k:
                found, subval = _get_nested_json_value(actual, k)
                if not found:
                    return False, f"Expected key '{k}' not found in JSON"
                match, err = _match_json_structure(v, subval, subpath)
                if not match:
                    return False, err
                continue

            if k not in actual:
                return False, f"Expected JSON key '{k}' missing from response"
            match, err = _match_json_structure(v, actual[k], subpath)
            if not match:
                return False, err
        return True, None

    if actual != expected:
        return False, f"Expected JSON {path} = {expected!r}, got {actual!r}"

    return True, None


async def get_ssl_days_left(url: str, timeout: float = 5.0) -> int:
    """Inspect the SSL certificate of an HTTPS URL and return remaining valid days."""
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        return 9999

    host = parsed.hostname or ""
    port = parsed.port or 443
    loop = asyncio.get_running_loop()

    def _probe_ssl() -> int:
        context = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                if not cert or not isinstance(cert, dict):
                    return 0
                not_after_val = cert.get("notAfter")
                if not isinstance(not_after_val, str):
                    return 0
                # Format: 'May 26 23:59:59 2026 GMT'
                expire_date = datetime.strptime(not_after_val, "%b %d %H:%M:%S %Y %Z").replace(
                    tzinfo=timezone.utc
                )
                now = datetime.now(timezone.utc)
                delta = expire_date - now
                return max(0, delta.days)

    return await loop.run_in_executor(None, _probe_ssl)


class BaseAssertion(ABC):
    """Abstract contract for an HTTP health check assertion."""

    @abstractmethod
    async def validate(
        self,
        response: httpx.Response,
        latency_ms: float,
        expect: ExpectConfig,
        url: str,
        timeout: float,
    ) -> tuple[bool, str | None, int | None]:
        """Validate response against rule.

        Returns:
            Tuple of (passed, error_reason, ssl_days_left).
        """


class StatusCodeAssertion(BaseAssertion):
    """Validates HTTP status code against expectation."""

    async def validate(
        self,
        response: httpx.Response,
        latency_ms: float,
        expect: ExpectConfig,
        url: str,
        timeout: float,
    ) -> tuple[bool, str | None, int | None]:
        passed, reason = _check_status_code(expect.status_code, response.status_code)
        return passed, reason, None


class LatencyAssertion(BaseAssertion):
    """Validates that round-trip response latency does not exceed configured ceiling."""

    async def validate(
        self,
        response: httpx.Response,
        latency_ms: float,
        expect: ExpectConfig,
        url: str,
        timeout: float,
    ) -> tuple[bool, str | None, int | None]:
        if expect.max_latency_ms is not None and latency_ms > expect.max_latency_ms:
            reason = f"Response latency {latency_ms:.0f} ms exceeded limit {expect.max_latency_ms:.0f} ms"
            return False, reason, None
        return True, None, None


class TextContentAssertion(BaseAssertion):
    """Validates presence of required text substring in response body."""

    async def validate(
        self,
        response: httpx.Response,
        latency_ms: float,
        expect: ExpectConfig,
        url: str,
        timeout: float,
    ) -> tuple[bool, str | None, int | None]:
        if expect.contains_text is not None and expect.contains_text not in response.text:
            return False, f"Missing expected text: '{expect.contains_text}'", None
        return True, None, None


class RegexAssertion(BaseAssertion):
    """Validates that response body matches regular expression pattern."""

    async def validate(
        self,
        response: httpx.Response,
        latency_ms: float,
        expect: ExpectConfig,
        url: str,
        timeout: float,
    ) -> tuple[bool, str | None, int | None]:
        if expect.regex is not None and not re.search(expect.regex, response.text):
            return False, f"Response body failed to match regex: '{expect.regex}'", None
        return True, None, None


class JsonAssertion(BaseAssertion):
    """Validates JSON response body against expected structure and keys."""

    async def validate(
        self,
        response: httpx.Response,
        latency_ms: float,
        expect: ExpectConfig,
        url: str,
        timeout: float,
    ) -> tuple[bool, str | None, int | None]:
        if expect.json_match is None:
            return True, None, None
        try:
            parsed_json = response.json()
        except Exception:
            return False, "Response body is not valid JSON", None

        matched, json_err = _match_json_structure(expect.json_match, parsed_json)
        if not matched:
            return False, json_err, None
        return True, None, None


class SslCertificateAssertion(BaseAssertion):
    """Validates TLS certificate validity and impending expiration."""

    async def validate(
        self,
        response: httpx.Response,
        latency_ms: float,
        expect: ExpectConfig,
        url: str,
        timeout: float,
    ) -> tuple[bool, str | None, int | None]:
        if not (expect.ssl_check and url.lower().startswith("https://")):
            return True, None, None

        try:
            # Delegate through module-level function to honor any monkeypatching in tests
            ssl_days = await get_ssl_days_left(url, timeout=min(timeout, 5.0))
            if ssl_days <= expect.ssl_warn_days:
                reason = (
                    f"SSL certificate expires in {ssl_days} days "
                    f"(threshold: {expect.ssl_warn_days} days)"
                )
                return False, reason, ssl_days
            return True, None, ssl_days
        except Exception as exc:
            return False, f"SSL certificate check failed: {exc}", None


class HttpAssertionPipeline:
    """Executes an ordered pipeline of assertions against an HTTP response."""

    def __init__(self, assertions: list[BaseAssertion] | None = None) -> None:
        self.assertions = assertions or [
            StatusCodeAssertion(),
            LatencyAssertion(),
            TextContentAssertion(),
            RegexAssertion(),
            JsonAssertion(),
            SslCertificateAssertion(),
        ]

    async def run(
        self,
        response: httpx.Response,
        latency_ms: float,
        expect: ExpectConfig,
        url: str,
        timeout: float,
    ) -> tuple[bool, str | None, int | None]:
        """Run all assertions in sequence. Short-circuit on the first failure."""
        ssl_days_detected: int | None = None
        for assertion in self.assertions:
            passed, reason, ssl_days = await assertion.validate(
                response=response,
                latency_ms=latency_ms,
                expect=expect,
                url=url,
                timeout=timeout,
            )
            if ssl_days is not None:
                ssl_days_detected = ssl_days
            if not passed:
                return False, reason, ssl_days_detected
        return True, None, ssl_days_detected


# ---------------------------------------------------------------------------
# Polymorphic Probes
# ---------------------------------------------------------------------------

class BaseProbe(ABC):
    """Abstract base class for all endpoint health probes."""

    @abstractmethod
    async def check(self) -> CheckResult:
        """Execute the probe and return health check result."""


class HttpProbe(BaseProbe):
    """Health probe evaluating an HTTP target endpoint."""

    def __init__(
        self,
        target: TargetConfig,
        client: httpx.AsyncClient,
        pipeline: HttpAssertionPipeline | None = None,
    ) -> None:
        self.target = target
        self.client = client
        self.pipeline = pipeline or HttpAssertionPipeline()

    async def check(self) -> CheckResult:
        """Issue HTTP request and evaluate configured expectations."""
        url = self.target.url
        method = self.target.method
        timeout = self.target.timeout or 10.0
        headers = dict(self.target.headers)
        body = self.target.body
        expect = self.target.expect

        start_time = time.perf_counter()

        try:
            req_content = body.encode("utf-8") if body is not None else None
            response = await self.client.request(
                method=method,
                url=url,
                headers=headers,
                content=req_content,
                timeout=timeout,
                follow_redirects=self.target.follow_redirects,
            )
            latency_ms = (time.perf_counter() - start_time) * 1000.0
        except httpx.TimeoutException:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return CheckResult(
                passed=False,
                status_code=None,
                status_phrase="Timeout",
                latency_ms=latency_ms,
                error_reason=f"Connection timed out after {timeout:.1f}s",
                checked_at=datetime.now(timezone.utc),
            )
        except httpx.ConnectError as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return CheckResult(
                passed=False,
                status_code=None,
                status_phrase="Connection Failed",
                latency_ms=latency_ms,
                error_reason=f"Failed to connect to host: {exc}",
                checked_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return CheckResult(
                passed=False,
                status_code=None,
                status_phrase="Request Error",
                latency_ms=latency_ms,
                error_reason=str(exc),
                checked_at=datetime.now(timezone.utc),
            )

        status_code = response.status_code
        status_phrase = response.reason_phrase or "OK"

        passed, reason, ssl_days = await self.pipeline.run(
            response=response,
            latency_ms=latency_ms,
            expect=expect,
            url=url,
            timeout=timeout,
        )

        return CheckResult(
            passed=passed,
            status_code=status_code,
            status_phrase=status_phrase,
            latency_ms=latency_ms,
            error_reason=reason,
            ssl_days_left=ssl_days,
            checked_at=datetime.now(timezone.utc),
        )


class TcpProbe(BaseProbe):
    """Health probe evaluating socket connectivity to a TCP host and port."""

    def __init__(self, target: TCPTargetConfig) -> None:
        self.target = target

    async def check(self) -> CheckResult:
        """Attempt TCP connection handshake and measure latency."""
        timeout = self.target.timeout or 5.0
        start_time = time.perf_counter()

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.target.host, self.target.port),
                timeout=timeout,
            )
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

            return CheckResult(
                passed=True,
                status_code=None,
                status_phrase="Connected",
                latency_ms=latency_ms,
                checked_at=datetime.now(timezone.utc),
            )
        except asyncio.TimeoutError:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return CheckResult(
                passed=False,
                status_code=None,
                status_phrase="Timeout",
                latency_ms=latency_ms,
                error_reason=f"TCP connection timed out after {timeout:.1f}s",
                checked_at=datetime.now(timezone.utc),
            )
        except ConnectionRefusedError:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return CheckResult(
                passed=False,
                status_code=None,
                status_phrase="Connection Refused",
                latency_ms=latency_ms,
                error_reason=f"Connection refused on {self.target.host}:{self.target.port}",
                checked_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return CheckResult(
                passed=False,
                status_code=None,
                status_phrase="Connection Failed",
                latency_ms=latency_ms,
                error_reason=str(exc),
                checked_at=datetime.now(timezone.utc),
            )


# ---------------------------------------------------------------------------
# Public Facade Functions (Preserving 100% Backward Compatibility)
# ---------------------------------------------------------------------------

async def evaluate_target(target: TargetConfig, client: httpx.AsyncClient) -> CheckResult:
    """Execute target request and evaluate health expectations via HttpProbe."""
    return await HttpProbe(target, client).check()


async def evaluate_tcp_target(target: TCPTargetConfig) -> CheckResult:
    """Evaluate socket connectivity to a TCP host and port via TcpProbe."""
    return await TcpProbe(target).check()
