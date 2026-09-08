"""Interactive terminal dashboard (TUI) for real-time monitoring."""

from __future__ import annotations

from datetime import datetime
import time
from typing import TYPE_CHECKING

from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sentinel.state import TargetStatus, format_duration

if TYPE_CHECKING:
    from sentinel.engine import SentinelEngine


class LatencyBarRenderer:
    """Renders colored spark/meter latency bars for terminal presentation."""

    BAR_CHARS = " ▂▃▄▅▆▇█"

    @classmethod
    def render_bar(cls, latency_ms: float, max_scale: float = 1000.0) -> str:
        """Render a text latency indicator with color coding."""
        ratio = min(1.0, max(0.0, latency_ms / max_scale))
        blocks = int(ratio * (len(cls.BAR_CHARS) - 1))
        char = cls.BAR_CHARS[min(blocks, len(cls.BAR_CHARS) - 1)]

        rounded_ms = int(latency_ms)
        if latency_ms < 200:
            return f"[green]{char} {rounded_ms}ms[/green]"
        if latency_ms < 600:
            return f"[yellow]{char} {rounded_ms}ms[/yellow]"
        return f"[red]{char} {rounded_ms}ms[/red]"


def _get_latency_bar(latency_ms: float, max_scale: float = 1000.0) -> str:
    """Backward-compatible helper function delegating to LatencyBarRenderer."""
    return LatencyBarRenderer.render_bar(latency_ms, max_scale)


class SentinelDashboard:
    """Renders a real-time Rich layout for the monitoring daemon."""

    def __init__(self, engine: SentinelEngine) -> None:
        self.engine = engine
        self.start_time = time.time()
        self.events: list[tuple[str, str, str]] = []  # (timestamp, level, message)

    def record_event(self, level: str, message: str) -> None:
        """Add an event to the recent event log, maintaining a maximum history."""
        ts = datetime.now().strftime("%H:%M:%S")
        self.events.append((ts, level, message))
        if len(self.events) > 8:
            self.events.pop(0)

    def _render_header(self) -> Panel:
        """Render the top status bar with daemon uptime and channel health."""
        elapsed = format_duration(time.time() - self.start_time)
        states = list(self.engine.states.values())
        total = len(states)
        healthy = sum(1 for s in states if s.status == TargetStatus.UP)
        avg_uptime = (sum(s.uptime_percentage for s in states) / total) if total > 0 else 100.0

        channels: list[str] = []
        if self.engine.config.telegram.is_configured:
            channels.append("Telegram")
        if self.engine.config.webhook.is_configured:
            channels.append("Webhook")
        if self.engine.config.discord.is_configured:
            channels.append("Discord")
        if self.engine.config.slack.is_configured:
            channels.append("Slack")

        channel_str = ", ".join(channels) if channels else "None"

        text = Text()
        text.append("🛡️  SENTINEL MONITORING DAEMON", style="bold cyan")
        text.append(f"  |  Uptime: {elapsed}", style="dim")
        text.append(
            f"  |  Services: {healthy}/{total} Healthy",
            style="green" if healthy == total else "yellow",
        )
        text.append(f"  |  Avg Uptime: {avg_uptime:.1f}%", style="cyan")
        text.append(f"  |  Alert Channels: {channel_str}", style="dim")

        return Panel(text, style="blue")

    def _render_targets_table(self) -> Table:
        """Render the real-time matrix of monitored endpoints."""
        table = Table(expand=True, show_header=True, header_style="bold magenta")
        table.add_column("Target", style="cyan", ratio=2)
        table.add_column("Status", justify="center", width=8)
        table.add_column("Latency", justify="right", width=12)
        table.add_column("Avg Latency", justify="right", width=12)
        table.add_column("Uptime", justify="right", width=9)
        table.add_column("Failures", justify="center", width=9)
        table.add_column("Details", style="dim", ratio=3)

        for name, state in self.engine.states.items():
            if state.status == TargetStatus.UP:
                status = "[bold green]UP[/bold green]"
            elif state.status == TargetStatus.DOWN:
                status = "[bold red]DOWN[/bold red]"
            else:
                status = "[yellow]CHECK[/yellow]"

            lat_bar = LatencyBarRenderer.render_bar(state.last_latency_ms)
            avg_lat = f"{int(state.average_latency_ms)}ms"
            uptime_str = f"{state.uptime_percentage:.1f}%"
            fails_str = str(state.consecutive_failures)

            details = state.last_error_reason or "All checks passing"
            if state.last_status_code is not None:
                details = f"HTTP {state.last_status_code} - {details}"

            table.add_row(
                name,
                status,
                lat_bar,
                avg_lat,
                uptime_str,
                fails_str,
                details[:50] + ("..." if len(details) > 50 else ""),
            )

        return table

    def _render_event_log(self) -> Panel:
        """Render recent outage and recovery notifications."""
        table = Table(expand=True, show_header=False, box=None)
        table.add_column("Time", width=10, style="dim")
        table.add_column("Event")

        if not self.events:
            table.add_row("--:--:--", "[dim]Monitoring loop active. Waiting for events...[/dim]")
        else:
            for ts, level, msg in reversed(self.events):
                if level == "outage":
                    event_text = f"[bold red]OUTAGE[/bold red] {msg}"
                elif level == "recovery":
                    event_text = f"[bold green]RECOVERY[/bold green] {msg}"
                else:
                    event_text = f"[dim]{msg}[/dim]"
                table.add_row(ts, event_text)

        return Panel(table, title="Recent Alert Events", style="dim")

    def render(self) -> Layout:
        """Compose the complete dashboard layout."""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body", ratio=3),
            Layout(name="footer", size=8),
        )

        layout["header"].update(self._render_header())
        layout["body"].update(Panel(self._render_targets_table(), title="Monitored Endpoints"))
        layout["footer"].update(self._render_event_log())
        return layout
