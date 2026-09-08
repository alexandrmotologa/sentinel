"""Asynchronous monitoring engine, scheduler, and worker coordination."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import tempfile
import time

import httpx
from rich.console import Console

from sentinel.config import SentinelConfig, TargetConfig
from sentinel.evaluator import create_async_client, evaluate_target
from sentinel.notifier import AlertDispatcher
from sentinel.state import TargetState, TargetStatus


logger = logging.getLogger("sentinel.engine")
console = Console()


def get_heartbeat_path() -> Path:
    """Return the system path for the daemon heartbeat probe."""
    override = os.environ.get("SENTINEL_HEARTBEAT_PATH")
    if override:
        return Path(override)
    temp_dir = Path(tempfile.gettempdir())
    return temp_dir / "sentinel.heartbeat"


def write_heartbeat() -> None:
    """Touch the heartbeat file with current unix timestamp."""
    try:
        path = get_heartbeat_path()
        path.write_text(str(time.time()), encoding="utf-8")
    except Exception as exc:
        logger.debug("Failed writing heartbeat: %s", exc)


def is_daemon_healthy(max_age_seconds: float = 120.0) -> bool:
    """Check if the heartbeat file was updated within max_age_seconds."""
    path = get_heartbeat_path()
    if not path.exists():
        return False
    try:
        content = path.read_text(encoding="utf-8").strip()
        last_beat = float(content)
        return (time.time() - last_beat) <= max_age_seconds
    except Exception:
        return False


class SentinelEngine:
    """Coordinates concurrent target monitoring loops and alerting."""

    def __init__(self, config: SentinelConfig) -> None:
        self.config = config
        self.notifier = AlertDispatcher(config.telegram, config.webhook)
        self.states: dict[str, TargetState] = {
            target.name: TargetState(name=target.name, url=target.url)
            for target in config.targets
        }
        self.running = False
        self._stop_event = asyncio.Event()

    def get_state(self, name: str) -> TargetState | None:
        return self.states.get(name)

    async def _run_target_loop(self, target: TargetConfig, client: httpx.AsyncClient) -> None:
        """Independently checks a target on its scheduled interval."""
        state = self.states[target.name]
        debounce = self.config.global_config.consecutive_failures_to_alert
        interval = target.interval or 60.0

        while not self._stop_event.is_set():
            result = await evaluate_target(target, client)
            should_outage, should_recovery = state.update(result, debounce)
            write_heartbeat()

            # Format console log line
            ts_str = datetime.now().strftime("%H:%M:%S")
            if result.passed:
                console.print(
                    f"[[dim]{ts_str}[/dim]] [green]PASS[/green] {target.name} "
                    f"([cyan]{int(result.latency_ms)}ms[/cyan]) [dim]{target.url}[/dim]"
                )
            else:
                reason = result.error_reason or "Check failed"
                status_disp = result.http_status_text
                console.print(
                    f"[[dim]{ts_str}[/dim]] [red]FAIL[/red] {target.name} "
                    f"[{state.consecutive_failures}/{debounce}] "
                    f"[yellow]{status_disp}[/yellow] - {reason}"
                )

            if should_outage:
                console.print(f"[bold red]>>> Outage alert dispatched for {target.name}[/bold red]")
                asyncio.create_task(self.notifier.send_outage_alert(state, debounce))

            if should_recovery:
                console.print(f"[bold green]>>> Recovery alert dispatched for {target.name}[/bold green]")
                asyncio.create_task(self.notifier.send_recovery_alert(state))

            # Sleep until next check or stop signal
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _run_daily_summary_loop(self) -> None:
        """Sends daily summary notifications at the configured UTC time."""
        target_time_str = self.config.global_config.daily_summary_time
        if not target_time_str or not self.notifier.config.is_configured:
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
                # Time to fire daily summary
                states_list = list(self.states.values())
                console.print("[bold blue]>>> Dispatching daily summary report[/bold blue]")
                await self.notifier.send_daily_summary(states_list)
                # Sleep briefly to avoid double-firing within the same minute
                await asyncio.sleep(65.0)

    async def run(self) -> None:
        """Start the async engine and monitor all configured targets concurrently."""
        self.running = True
        self._stop_event.clear()
        write_heartbeat()

        console.print(
            f"[bold cyan]Sentinel started[/bold cyan] "
            f"monitoring [yellow]{len(self.config.targets)}[/yellow] targets "
            f"(Debounce: {self.config.global_config.consecutive_failures_to_alert})"
        )

        limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
        async with create_async_client(limits=limits) as client:
            tasks: list[asyncio.Task[None]] = []

            for target in self.config.targets:
                task = asyncio.create_task(
                    self._run_target_loop(target, client),
                    name=f"sentinel-target-{target.name}",
                )
                tasks.append(task)

            summary_task = asyncio.create_task(
                self._run_daily_summary_loop(),
                name="sentinel-daily-summary",
            )
            tasks.append(summary_task)

            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.CancelledError:
                pass
            finally:
                self.running = False
                console.print("[dim]Sentinel engine stopped.[/dim]")

    def stop(self) -> None:
        """Signal the engine to stop gracefully."""
        self._stop_event.set()
