"""Command-line interface for Sentinel using Typer and Rich."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Optional

import httpx
import typer
from rich.console import Console
from rich.table import Table

from sentinel import __version__
from sentinel.config import SentinelConfig, TargetConfig
from sentinel.engine import SentinelEngine, is_daemon_healthy
from sentinel.evaluator import CheckResult, create_async_client, evaluate_target
from sentinel.notifier import AlertDispatcher, TelegramNotifier


app = typer.Typer(
    name="sentinel",
    help="Sentinel: 24/7 Lightweight Async Uptime & Health Watcher",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


def version_callback(value: bool) -> None:
    if value:
        console.print(f"Sentinel v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """Sentinel 24/7 Async Health & Uptime Watcher."""
    pass


@app.command(name="check-config")
def check_config(
    config_path: Path = typer.Argument(
        Path("sites.yaml"),
        help="Path to the YAML configuration file",
        exists=False,
    ),
) -> None:
    """Validate YAML configuration file syntax and assertion rules."""
    if not config_path.exists():
        console.print(f"[bold red]Error:[/bold red] File not found: {config_path}")
        raise typer.Exit(code=1)

    try:
        cfg = SentinelConfig.load_yaml(config_path)
    except Exception as exc:
        console.print(f"[bold red]Configuration error in {config_path}:[/bold red]\n{exc}")
        raise typer.Exit(code=1)

    console.print(f"[bold green]Configuration valid:[/bold green] {config_path}")
    console.print(
        f"Default interval: [cyan]{cfg.global_config.default_interval:.0f}s[/cyan] | "
        f"Default timeout: [cyan]{cfg.global_config.default_timeout:.0f}s[/cyan] | "
        f"Debounce: [yellow]{cfg.global_config.consecutive_failures_to_alert}[/yellow] failures"
    )

    tg_status = "[green]Enabled[/green]" if cfg.telegram.is_configured else "[yellow]Not Configured[/yellow]"
    wh_status = "[green]Enabled[/green]" if cfg.webhook.is_configured else "[yellow]Not Configured[/yellow]"
    console.print(f"Telegram alerts: {tg_status} | Webhook alerts: {wh_status}")

    table = Table(title="Configured Targets", show_header=True, header_style="bold magenta")
    table.add_column("Target Name", style="cyan")
    table.add_column("Method", style="green", width=7)
    table.add_column("URL")
    table.add_column("Interval", justify="right")
    table.add_column("Expectation Rules")

    for t in cfg.targets:
        rules: list[str] = []
        if t.expect.status_code is not None:
            rules.append(f"code={t.expect.status_code}")
        if t.expect.max_latency_ms is not None:
            rules.append(f"latency<={int(t.expect.max_latency_ms)}ms")
        if t.expect.contains_text:
            rules.append(f"text='{t.expect.contains_text[:15]}...'")
        if t.expect.json_match:
            rules.append("json-path")
        if t.expect.ssl_check:
            rules.append(f"ssl<={t.expect.ssl_warn_days}d")

        rule_summary = ", ".join(rules) if rules else "default (status 200)"
        table.add_row(
            t.name,
            t.method,
            t.url,
            f"{t.interval:.0f}s",
            rule_summary,
        )

    console.print(table)


@app.command(name="test-alert")
def test_alert(
    config_path: Path = typer.Option(
        Path("sites.yaml"),
        "--config",
        "-c",
        help="Path to the YAML configuration file",
    ),
) -> None:
    """Send a test alert message to Telegram to verify credentials."""
    if not config_path.exists():
        console.print(f"[bold red]Error:[/bold red] File not found: {config_path}")
        raise typer.Exit(code=1)

    try:
        cfg = SentinelConfig.load_yaml(config_path)
    except Exception as exc:
        console.print(f"[bold red]Configuration error:[/bold red] {exc}")
        raise typer.Exit(code=1)

    if not cfg.telegram.is_configured and not cfg.webhook.is_configured:
        console.print(
            "[bold yellow]Warning:[/bold yellow] Neither Telegram nor Webhook is configured."
        )
        raise typer.Exit(code=1)

    console.print("[cyan]Sending test alert...[/cyan]")
    dispatcher = AlertDispatcher(cfg.telegram, cfg.webhook)

    async def _send() -> bool:
        return await dispatcher.send_test_alert()

    success = asyncio.run(_send())
    if success:
        console.print("[bold green]Test alert successfully delivered![/bold green]")
    else:
        console.print("[bold red]Failed to deliver test alert. Check channel credentials.[/bold red]")
        raise typer.Exit(code=1)


@app.command(name="probe")
def probe(
    config_path: Path = typer.Argument(
        Path("sites.yaml"),
        help="Path to the YAML configuration file",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Output probe results as JSON",
    ),
) -> None:
    """Execute a one-off immediate health check across all targets."""
    if not config_path.exists():
        console.print(f"[bold red]Error:[/bold red] File not found: {config_path}")
        raise typer.Exit(code=1)

    try:
        cfg = SentinelConfig.load_yaml(config_path)
    except Exception as exc:
        console.print(f"[bold red]Configuration error:[/bold red] {exc}")
        raise typer.Exit(code=1)

    if not cfg.targets:
        console.print("[bold yellow]No targets defined.[/bold yellow]")
        raise typer.Exit(code=1)

    async def _run_probes() -> list[tuple[Any, CheckResult]]:
        async with create_async_client() as client:
            tasks = [evaluate_target(t, client) for t in cfg.targets]
            results = await asyncio.gather(*tasks)
            return list(zip(cfg.targets, results))

    results = asyncio.run(_run_probes())
    all_passed = all(res.passed for _, res in results)

    if as_json:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "all_passed": all_passed,
            "targets": [
                {
                    "name": t.name,
                    "url": t.url,
                    "passed": res.passed,
                    "status_code": res.status_code,
                    "status_phrase": res.status_phrase,
                    "latency_ms": round(res.latency_ms, 2),
                    "error_reason": res.error_reason,
                    "ssl_days_left": res.ssl_days_left,
                }
                for t, res in results
            ],
        }
        print(json.dumps(payload, indent=2))
        if not all_passed:
            raise typer.Exit(code=1)
        return

    table = Table(title="Target Probe Results", show_header=True, header_style="bold magenta")
    table.add_column("Target Name", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("HTTP Code", justify="center")
    table.add_column("Latency", justify="right")
    table.add_column("Details")

    for t, res in results:
        status_tag = "[green]PASS[/green]" if res.passed else "[red]FAIL[/red]"
        code_str = str(res.status_code) if res.status_code is not None else "-"
        latency_str = f"{int(res.latency_ms)}ms"
        details = res.error_reason if not res.passed else "Healthy"
        table.add_row(t.name, status_tag, code_str, latency_str, details)

    console.print(table)
    if not all_passed:
        raise typer.Exit(code=1)


@app.command(name="run")
def run(
    config_path: Path = typer.Argument(
        Path("sites.yaml"),
        help="Path to the YAML configuration file",
    ),
) -> None:
    """Start the Sentinel 24/7 monitoring daemon."""
    if not config_path.exists():
        console.print(f"[bold red]Error:[/bold red] File not found: {config_path}")
        raise typer.Exit(code=1)

    try:
        cfg = SentinelConfig.load_yaml(config_path)
    except Exception as exc:
        console.print(f"[bold red]Failed loading configuration:[/bold red] {exc}")
        raise typer.Exit(code=1)

    if not cfg.targets:
        console.print("[bold yellow]No targets defined in configuration.[/bold yellow]")
        raise typer.Exit(code=1)

    engine = SentinelEngine(cfg)

    try:
        asyncio.run(engine.run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutdown signal received. Stopping Sentinel...[/yellow]")
        engine.stop()


@app.command(name="healthcheck")
def healthcheck(
    max_age: float = typer.Option(
        120.0,
        "--max-age",
        help="Maximum allowed age of heartbeat file in seconds",
    ),
) -> None:
    """Check if the Sentinel monitoring daemon is alive and updating its heartbeat."""
    if is_daemon_healthy(max_age_seconds=max_age):
        console.print("[green]OK: Daemon heartbeat is fresh.[/green]")
        sys.exit(0)
    else:
        console.print("[red]ERROR: Daemon heartbeat is stale or missing.[/red]")
        sys.exit(1)


if __name__ == "__main__":
    app()
