"""Asynchronous monitoring engine, scheduler, worker coordination, and config reloading."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import tempfile
import time
from typing import TYPE_CHECKING

import httpx
from rich.console import Console

from sentinel.config import SentinelConfig, TargetConfig, TCPTargetConfig
from sentinel.evaluator import BaseProbe, HttpProbe, TcpProbe, create_async_client
from sentinel.notifier import AlertDispatcher
from sentinel.server import MetricsServer
from sentinel.state import TargetState

if TYPE_CHECKING:
    from sentinel.dashboard import SentinelDashboard


logger = logging.getLogger("sentinel.engine")
console = Console()


class HeartbeatService:
    """Encapsulates daemon liveness heartbeat file operations."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path

    def get_path(self) -> Path:
        """Return the filesystem path for the daemon heartbeat file."""
        if self._path is not None:
            return self._path
        override = os.environ.get("SENTINEL_HEARTBEAT_PATH")
        if override:
            return Path(override)
        temp_dir = Path(tempfile.gettempdir())
        return temp_dir / "sentinel.heartbeat"

    def write(self) -> None:
        """Touch the heartbeat file with current unix timestamp."""
        try:
            path = self.get_path()
            path.write_text(str(time.time()), encoding="utf-8")
        except Exception as exc:
            logger.debug("Failed writing heartbeat: %s", exc)

    def is_healthy(self, max_age_seconds: float = 120.0) -> bool:
        """Check if the heartbeat file was refreshed within max_age_seconds."""
        path = self.get_path()
        if not path.exists():
            return False
        try:
            content = path.read_text(encoding="utf-8").strip()
            last_beat = float(content)
            return (time.time() - last_beat) <= max_age_seconds
        except Exception:
            return False


# Default module-level singleton instance for backward compatibility
default_heartbeat = HeartbeatService()


def get_heartbeat_path() -> Path:
    """Return the system path for the daemon heartbeat probe."""
    return default_heartbeat.get_path()


def write_heartbeat() -> None:
    """Touch the heartbeat file with current unix timestamp."""
    default_heartbeat.write()


def is_daemon_healthy(max_age_seconds: float = 120.0) -> bool:
    """Check if the heartbeat file was updated within max_age_seconds."""
    return default_heartbeat.is_healthy(max_age_seconds)


class TargetWorker:
    """Manages the periodic execution lifecycle of a single target's probe."""

    def __init__(
        self,
        name: str,
        probe: BaseProbe,
        state: TargetState,
        interval: float,
        debounce_threshold: int,
        notifier: AlertDispatcher,
        stop_event: asyncio.Event,
        heartbeat: HeartbeatService = default_heartbeat,
        dashboard: SentinelDashboard | None = None,
        is_tcp: bool = False,
        display_endpoint: str = "",
    ) -> None:
        self.name = name
        self.probe = probe
        self.state = state
        self.interval = interval
        self.debounce_threshold = debounce_threshold
        self.notifier = notifier
        self.stop_event = stop_event
        self.heartbeat = heartbeat
        self.dashboard = dashboard
        self.is_tcp = is_tcp
        self.display_endpoint = display_endpoint

    def _log_console_check(self, result_passed: bool, latency_ms: float, error_reason: str | None, status_text: str) -> None:
        """Print colored check outcome to console when dashboard is not active."""
        ts_str = datetime.now().strftime("%H:%M:%S")
        proto_tag = " [bold blue]TCP[/bold blue]" if self.is_tcp else ""
        if result_passed:
            console.print(
                f"[[dim]{ts_str}[/dim]] [green]PASS[/green]{proto_tag} {self.name} "
                f"([cyan]{int(latency_ms)}ms[/cyan]) [dim]{self.display_endpoint}[/dim]"
            )
        else:
            reason = error_reason or "Check failed"
            status_disp = f"[yellow]{status_text}[/yellow] - " if status_text else ""
            console.print(
                f"[[dim]{ts_str}[/dim]] [red]FAIL[/red]{proto_tag} {self.name} "
                f"[{self.state.consecutive_failures}/{self.debounce_threshold}] "
                f"{status_disp}{reason}"
            )

    async def run(self) -> None:
        """Execute scheduled monitoring loop until stop_event is signaled."""
        while not self.stop_event.is_set():
            result = await self.probe.check()
            should_outage, should_recovery = self.state.update(result, self.debounce_threshold)
            self.heartbeat.write()

            if not self.dashboard:
                self._log_console_check(
                    result_passed=result.passed,
                    latency_ms=result.latency_ms,
                    error_reason=result.error_reason,
                    status_text=result.http_status_text if not self.is_tcp else "",
                )

            if should_outage:
                if self.dashboard:
                    prefix = "TCP " if self.is_tcp else ""
                    self.dashboard.record_event(
                        "outage", f"{prefix}{self.name} failed: {result.error_reason}"
                    )
                else:
                    prefix = "TCP " if self.is_tcp else ""
                    console.print(f"[bold red]>>> Outage alert dispatched for {prefix}{self.name}[/bold red]")
                asyncio.create_task(
                    self.notifier.send_outage_alert(self.state, self.debounce_threshold)
                )

            if should_recovery:
                if self.dashboard:
                    prefix = "TCP " if self.is_tcp else ""
                    self.dashboard.record_event("recovery", f"{prefix}{self.name} recovered")
                else:
                    prefix = "TCP " if self.is_tcp else ""
                    console.print(f"[bold green]>>> Recovery alert dispatched for {prefix}{self.name}[/bold green]")
                asyncio.create_task(self.notifier.send_recovery_alert(self.state))

            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass


class SentinelEngine:
    """Coordinates concurrent target monitoring loops, workers, and alerting."""

    def __init__(self, config: SentinelConfig) -> None:
        self.config = config
        self.heartbeat = default_heartbeat
        self.notifier = AlertDispatcher(
            config.telegram,
            config.webhook,
            config.discord,
            config.slack,
        )
        self.states: dict[str, TargetState] = {}
        for target in config.targets:
            self.states[target.name] = TargetState(name=target.name, url=target.url)
        for tcp in config.tcp_targets:
            self.states[tcp.name] = TargetState(name=tcp.name, url=f"tcp://{tcp.host}:{tcp.port}")

        self.running = False
        self._stop_event = asyncio.Event()
        self.dashboard: SentinelDashboard | None = None
        self._worker_tasks: dict[str, asyncio.Task[None]] = {}
        self._client: httpx.AsyncClient | None = None

        self.metrics_server: MetricsServer | None = None
        if config.metrics.enabled:
            self.metrics_server = MetricsServer(
                config.metrics.host,
                config.metrics.port,
                lambda: self.states,
            )

    def get_state(self, name: str) -> TargetState | None:
        """Retrieve the current TargetState for a given target name."""
        return self.states.get(name)

    async def _run_target_loop(self, target: TargetConfig, client: httpx.AsyncClient) -> None:
        """Run worker loop for an HTTP target (delegates to polymorphic TargetWorker)."""
        state = self.states[target.name]
        probe = HttpProbe(target, client)
        worker = TargetWorker(
            name=target.name,
            probe=probe,
            state=state,
            interval=target.interval or 60.0,
            debounce_threshold=self.config.global_config.consecutive_failures_to_alert,
            notifier=self.notifier,
            stop_event=self._stop_event,
            heartbeat=self.heartbeat,
            dashboard=self.dashboard,
            is_tcp=False,
            display_endpoint=target.url,
        )
        await worker.run()

    async def _run_tcp_target_loop(self, target: TCPTargetConfig) -> None:
        """Run worker loop for a TCP target (delegates to polymorphic TargetWorker)."""
        state = self.states[target.name]
        probe = TcpProbe(target)
        worker = TargetWorker(
            name=target.name,
            probe=probe,
            state=state,
            interval=target.interval or 60.0,
            debounce_threshold=self.config.global_config.consecutive_failures_to_alert,
            notifier=self.notifier,
            stop_event=self._stop_event,
            heartbeat=self.heartbeat,
            dashboard=self.dashboard,
            is_tcp=True,
            display_endpoint=f"{target.host}:{target.port}",
        )
        await worker.run()

    async def _run_daily_summary_loop(self) -> None:
        """Sends daily summary notifications at the configured UTC time."""
        target_time_str = self.config.global_config.daily_summary_time
        if not target_time_str or not self.notifier.is_configured:
            return

        target_hour, target_min = map(int, target_time_str.split(":"))

        while not self._stop_event.is_set():
            now = datetime.now(timezone.utc)
            target_today = now.replace(
                hour=target_hour, minute=target_min, second=0, microsecond=0
            )

            if now >= target_today:
                seconds_until = (target_today.timestamp() + 86400) - now.timestamp()
            else:
                seconds_until = target_today.timestamp() - now.timestamp()

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=seconds_until)
                break
            except asyncio.TimeoutError:
                states_list = list(self.states.values())
                if not self.dashboard:
                    console.print("[bold blue]>>> Dispatching daily summary report[/bold blue]")
                await self.notifier.send_daily_summary(states_list)
                await asyncio.sleep(65.0)

    def reload_config(self, new_config: SentinelConfig) -> None:
        """Dynamically synchronize target tasks with an updated configuration."""
        self.config = new_config
        self.notifier = AlertDispatcher(
            new_config.telegram,
            new_config.webhook,
            new_config.discord,
            new_config.slack,
        )

        current_http_names = {t.name: t for t in new_config.targets}
        current_tcp_names = {t.name: t for t in new_config.tcp_targets}
        all_new_names = set(current_http_names.keys()) | set(current_tcp_names.keys())

        # Remove targets that no longer exist
        for old_name in list(self.states.keys()):
            if old_name not in all_new_names:
                task = self._worker_tasks.pop(old_name, None)
                if task:
                    task.cancel()
                self.states.pop(old_name, None)
                logger.info("Removed target from active monitoring: %s", old_name)

        # Add or update HTTP targets
        for name, target in current_http_names.items():
            if name not in self.states:
                self.states[name] = TargetState(name=name, url=target.url)
            if self._client and name not in self._worker_tasks:
                t = asyncio.create_task(
                    self._run_target_loop(target, self._client),
                    name=f"sentinel-target-{name}",
                )
                self._worker_tasks[name] = t
                logger.info("Added new HTTP target: %s", name)

        # Add or update TCP targets
        for name, tcp in current_tcp_names.items():
            if name not in self.states:
                self.states[name] = TargetState(name=name, url=f"tcp://{tcp.host}:{tcp.port}")
            if self.running and name not in self._worker_tasks:
                t = asyncio.create_task(
                    self._run_tcp_target_loop(tcp),
                    name=f"sentinel-tcp-{name}",
                )
                self._worker_tasks[name] = t
                logger.info("Added new TCP target: %s", name)

    async def run(self) -> None:
        """Start the async engine and monitor all configured targets concurrently."""
        self.running = True
        self._stop_event.clear()
        self.heartbeat.write()

        if self.metrics_server:
            await self.metrics_server.start()

        if not self.dashboard:
            total_count = len(self.config.targets) + len(self.config.tcp_targets)
            console.print(
                f"[bold cyan]Sentinel started[/bold cyan] "
                f"monitoring [yellow]{total_count}[/yellow] targets "
                f"({len(self.config.targets)} HTTP, {len(self.config.tcp_targets)} TCP)"
            )

        limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
        async with create_async_client(limits=limits) as client:
            self._client = client

            for target in self.config.targets:
                task = asyncio.create_task(
                    self._run_target_loop(target, client),
                    name=f"sentinel-target-{target.name}",
                )
                self._worker_tasks[target.name] = task

            for tcp in self.config.tcp_targets:
                task = asyncio.create_task(
                    self._run_tcp_target_loop(tcp),
                    name=f"sentinel-tcp-{tcp.name}",
                )
                self._worker_tasks[tcp.name] = task

            summary_task = asyncio.create_task(
                self._run_daily_summary_loop(),
                name="sentinel-daily-summary",
            )

            try:
                await asyncio.gather(
                    *self._worker_tasks.values(), summary_task, return_exceptions=True
                )
            except asyncio.CancelledError:
                pass
            finally:
                self.running = False
                if self.metrics_server:
                    await self.metrics_server.stop()
                if not self.dashboard:
                    console.print("[dim]Sentinel engine stopped.[/dim]")

    def stop(self) -> None:
        """Signal the engine to stop gracefully."""
        self._stop_event.set()
        for task in self._worker_tasks.values():
            task.cancel()
