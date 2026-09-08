"""Embedded asynchronous HTTP server for Prometheus metrics and health probes."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, Callable

from sentinel.state import TargetState, TargetStatus


logger = logging.getLogger("sentinel.server")


def generate_prometheus_metrics(states: dict[str, TargetState]) -> str:
    """Format in-memory target states into Prometheus text exposition format."""
    lines: list[str] = [
        "# HELP sentinel_target_up Target operational status (1 = UP, 0 = DOWN)",
        "# TYPE sentinel_target_up gauge",
    ]
    for name, state in states.items():
        val = 1 if state.status == TargetStatus.UP else 0
        target_escaped = name.replace('"', '\\"')
        lines.append(f'sentinel_target_up{{target="{target_escaped}"}} {val}')

    lines.extend([
        "",
        "# HELP sentinel_target_latency_seconds Round-trip latency in seconds",
        "# TYPE sentinel_target_latency_seconds gauge",
    ])
    for name, state in states.items():
        lat_sec = state.last_latency_ms / 1000.0
        target_escaped = name.replace('"', '\\"')
        lines.append(f'sentinel_target_latency_seconds{{target="{target_escaped}"}} {lat_sec:.6f}')

    lines.extend([
        "",
        "# HELP sentinel_target_consecutive_failures Number of consecutive failures",
        "# TYPE sentinel_target_consecutive_failures gauge",
    ])
    for name, state in states.items():
        target_escaped = name.replace('"', '\\"')
        lines.append(
            f'sentinel_target_consecutive_failures{{target="{target_escaped}"}} {state.consecutive_failures}'
        )

    lines.extend([
        "",
        "# HELP sentinel_target_uptime_ratio Target uptime ratio between 0.0 and 1.0",
        "# TYPE sentinel_target_uptime_ratio gauge",
    ])
    for name, state in states.items():
        ratio = state.uptime_percentage / 100.0
        target_escaped = name.replace('"', '\\"')
        lines.append(f'sentinel_target_uptime_ratio{{target="{target_escaped}"}} {ratio:.4f}')

    lines.extend([
        "",
        "# HELP sentinel_checks_total Total checks performed on target",
        "# TYPE sentinel_checks_total counter",
    ])
    for name, state in states.items():
        target_escaped = name.replace('"', '\\"')
        lines.append(f'sentinel_checks_total{{target="{target_escaped}"}} {state.total_checks}')

    lines.append("")
    return "\n".join(lines)


def generate_healthz_payload(states: dict[str, TargetState]) -> dict[str, Any]:
    """Format in-memory target states into JSON healthz representation."""
    all_up = all(s.status == TargetStatus.UP for s in states.values()) if states else True
    return {
        "status": "healthy" if all_up else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_targets": len(states),
        "healthy_targets": sum(1 for s in states.values() if s.status == TargetStatus.UP),
        "targets": {
            name: {
                "url": s.url,
                "status": s.status.value,
                "latency_ms": round(s.last_latency_ms, 2),
                "uptime_percentage": round(s.uptime_percentage, 2),
                "consecutive_failures": s.consecutive_failures,
                "last_error": s.last_error_reason,
            }
            for name, s in states.items()
        },
    }


class MetricsServer:
    """Lightweight zero-dependency async HTTP server serving /metrics and /healthz."""

    def __init__(
        self,
        host: str,
        port: int,
        state_provider: Callable[[], dict[str, TargetState]],
    ) -> None:
        self.host = host
        self.port = port
        self.state_provider = state_provider
        self.server: asyncio.Server | None = None

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            line = await reader.readline()
            if not line:
                writer.close()
                await writer.wait_closed()
                return

            request_line = line.decode("utf-8", errors="replace").strip()
            parts = request_line.split()
            path = parts[1] if len(parts) >= 2 else "/"

            # Drain headers
            while True:
                header_line = await reader.readline()
                if not header_line or header_line == b"\r\n" or header_line == b"\n":
                    break

            states = self.state_provider()

            if path in ("/metrics", "/metrics/"):
                body = generate_prometheus_metrics(states).encode("utf-8")
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: text/plain; version=0.0.4; charset=utf-8\r\n"
                    b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
                    b"Connection: close\r\n"
                    b"\r\n" + body
                )
            elif path in ("/healthz", "/health", "/healthz/"):
                payload = generate_healthz_payload(states)
                body = json.dumps(payload, indent=2).encode("utf-8")
                status_code = b"200 OK" if payload["status"] == "healthy" else b"503 Service Unavailable"
                response = (
                    b"HTTP/1.1 " + status_code + b"\r\n"
                    b"Content-Type: application/json; charset=utf-8\r\n"
                    b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
                    b"Connection: close\r\n"
                    b"\r\n" + body
                )
            else:
                body = b"Not Found\n"
                response = (
                    b"HTTP/1.1 404 Not Found\r\n"
                    b"Content-Type: text/plain; charset=utf-8\r\n"
                    b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
                    b"Connection: close\r\n"
                    b"\r\n" + body
                )

            writer.write(response)
            await writer.drain()
        except Exception as exc:
            logger.debug("Error handling HTTP server client: %s", exc)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def start(self) -> None:
        """Start listening for incoming HTTP connections."""
        self.server = await asyncio.start_server(
            self._handle_client, host=self.host, port=self.port
        )
        logger.info("Metrics server listening on http://%s:%d", self.host, self.port)

    async def stop(self) -> None:
        """Close server and wait for existing connections to terminate."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
