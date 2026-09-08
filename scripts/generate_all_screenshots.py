"""Generate production-grade terminal SVG and HTML snapshots of Sentinel."""

from __future__ import annotations

import io
import time
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table
import rich.terminal_theme as tt

from sentinel.cli import ConfigReportPresenter
from sentinel.config import SentinelConfig
from sentinel.dashboard import SentinelDashboard
from sentinel.engine import SentinelEngine
from sentinel.server import PrometheusExporter, HealthzExporter
from sentinel.state import TargetState, TargetStatus


def build_dashboard_svg(dest_svg: Path, dest_html: Path) -> None:
    buf = io.StringIO()
    console = Console(record=True, width=115, file=buf, force_terminal=True)
    cfg = SentinelConfig.load_yaml(Path("sites.example.yaml"))
    engine = SentinelEngine(cfg)

    # Populate realistic target states
    api_state = TargetState(name="Production API Health", url="https://api.example.com/health")
    api_state.total_checks = 480
    api_state.successful_checks = 480
    api_state.status = TargetStatus.UP
    api_state.last_latency_ms = 45.2
    api_state.last_status_code = 200
    api_state.uptime_seconds = 14400.0

    web_state = TargetState(name="Landing Page", url="https://example.com")
    web_state.total_checks = 240
    web_state.successful_checks = 239
    web_state.status = TargetStatus.UP
    web_state.last_latency_ms = 112.8
    web_state.last_status_code = 200
    web_state.ssl_days_left = 82
    web_state.uptime_seconds = 14340.0

    stripe_state = TargetState(name="Stripe Webhook Listener", url="https://hooks.example.com")
    stripe_state.total_checks = 320
    stripe_state.successful_checks = 310
    stripe_state.status = TargetStatus.DOWN
    stripe_state.consecutive_failures = 3
    stripe_state.last_latency_ms = 502.4
    stripe_state.last_status_code = 503
    stripe_state.last_error = "Expected status 200, got 503 Service Unavailable"
    stripe_state.down_since = datetime.now(timezone.utc)
    stripe_state.uptime_seconds = 13800.0

    pg_state = TargetState(name="Primary PostgreSQL", url="tcp://db.internal:5432")
    pg_state.total_checks = 480
    pg_state.successful_checks = 480
    pg_state.status = TargetStatus.UP
    pg_state.last_latency_ms = 12.1
    pg_state.uptime_seconds = 14400.0

    redis_state = TargetState(name="Redis Cache Cluster", url="tcp://127.0.0.1:6379")
    redis_state.total_checks = 960
    redis_state.successful_checks = 960
    redis_state.status = TargetStatus.UP
    redis_state.last_latency_ms = 2.4
    redis_state.uptime_seconds = 14400.0

    engine.states = {
        "Production API Health": api_state,
        "Landing Page": web_state,
        "Stripe Webhook Listener": stripe_state,
        "Primary PostgreSQL": pg_state,
        "Redis Cache Cluster": redis_state,
    }

    dash = SentinelDashboard(engine)
    dash.start_time = time.time() - 14400.0
    dash.record_event("info", "Daemon started with 5 targets (3 HTTP, 2 TCP)")
    dash.record_event("info", "Prometheus metrics server active on http://0.0.0.0:9090")
    dash.record_event("alert", "OUTAGE: Stripe Webhook Listener returned 503 Service Unavailable")
    dash.record_event("info", "Telegram alert dispatched to chat -100123456789")

    console.print(dash.render())
    svg = console.export_svg(title="sentinel run --dashboard sites.yaml", theme=tt.NIGHT_OWLISH)
    dest_svg.write_text(svg, encoding="utf-8")

    wrap_svg_in_html(svg, "Sentinel Live TUI Dashboard", dest_html)


def build_probe_svg(dest_svg: Path, dest_html: Path) -> None:
    buf = io.StringIO()
    console = Console(record=True, width=110, file=buf, force_terminal=True)
    console.print("[bold cyan]$ sentinel probe sites.yaml[/bold cyan]\n")

    table = Table(title="Target Probe Results", show_header=True, header_style="bold magenta")
    table.add_column("Type", style="yellow", width=6)
    table.add_column("Target Name", style="cyan", width=24)
    table.add_column("Status", justify="center", width=8)
    table.add_column("Code / Phrase", justify="center", width=14)
    table.add_column("Latency", justify="right", width=10)
    table.add_column("Details")

    probes = [
        ("HTTP", "Production API Gateway", True, 200, "OK", 42.1, "Healthy (json match: status=healthy)"),
        ("HTTP", "Marketing Landing Page", True, 200, "OK", 88.4, "Healthy (SSL expires in 82 days)"),
        ("HTTP", "Stripe Webhook Receiver", True, 204, "No Content", 134.2, "Healthy"),
        ("HTTP", "Legacy Auth Service", False, 502, "Bad Gateway", 312.0, "Expected status 200, got 502"),
        ("TCP", "Primary PostgreSQL", True, None, "Connected", 14.3, "TCP connection established"),
        ("TCP", "Redis Cache Cluster", True, None, "Connected", 3.8, "TCP connection established"),
    ]

    for p_type, name, passed, code, phrase, latency, details in probes:
        status_tag = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
        code_str = str(code) if code is not None else phrase
        latency_str = f"{latency:.1f}ms"
        table.add_row(p_type, name, status_tag, code_str, latency_str, details)

    console.print(table)
    console.print()
    console.print("[bold red]FAIL:[/bold red] 1 target check failed out of 6 (exit code 1)")

    svg = console.export_svg(title="sentinel probe sites.yaml", theme=tt.NIGHT_OWLISH)
    dest_svg.write_text(svg, encoding="utf-8")
    wrap_svg_in_html(svg, "Sentinel One-Off Target Probe", dest_html)


def build_check_config_svg(dest_svg: Path, dest_html: Path) -> None:
    buf = io.StringIO()
    console = Console(record=True, width=110, file=buf, force_terminal=True)
    console.print("[bold cyan]$ sentinel check-config sites.yaml[/bold cyan]\n")

    cfg = SentinelConfig.load_yaml(Path("sites.example.yaml"))
    import sentinel.cli
    orig_console = sentinel.cli.console
    sentinel.cli.console = console
    try:
        ConfigReportPresenter.render_summary(cfg, Path("sites.yaml"))
    finally:
        sentinel.cli.console = orig_console

    svg = console.export_svg(title="sentinel check-config sites.yaml", theme=tt.NIGHT_OWLISH)
    dest_svg.write_text(svg, encoding="utf-8")
    wrap_svg_in_html(svg, "Sentinel Configuration Report", dest_html)


def build_metrics_svg(dest_svg: Path, dest_html: Path) -> None:
    buf = io.StringIO()
    console = Console(record=True, width=110, file=buf, force_terminal=True)
    console.print("[bold cyan]$ curl -s http://127.0.0.1:9090/healthz | jq .[/bold cyan]")

    states = {
        "Production API Health": TargetState(name="Production API Health", url="https://api.example.com/health"),
        "Landing Page": TargetState(name="Landing Page", url="https://example.com"),
    }
    states["Production API Health"].status = TargetStatus.UP
    states["Landing Page"].status = TargetStatus.UP

    healthz_data = HealthzExporter.format_payload(states)
    import json
    console.print(f"[green]{json.dumps(healthz_data, indent=2)}[/green]\n")

    console.print("[bold cyan]$ curl -s http://127.0.0.1:9090/metrics | grep -E '^#|sentinel_' | head -n 14[/bold cyan]")
    metrics_str = PrometheusExporter.format_metrics(states)
    for line in metrics_str.strip().split("\n")[:12]:
        if line.startswith("# HELP") or line.startswith("# TYPE"):
            console.print(f"[dim]{line}[/dim]")
        elif " 1" in line:
            console.print(f"[green]{line}[/green]")
        else:
            console.print(f"[yellow]{line}[/yellow]")

    svg = console.export_svg(title="sentinel metrics server — /healthz & /metrics", theme=tt.NIGHT_OWLISH)
    dest_svg.write_text(svg, encoding="utf-8")
    wrap_svg_in_html(svg, "Sentinel Prometheus & Healthz Exporter", dest_html)


def wrap_svg_in_html(svg_content: str, page_title: str, output_path: Path) -> None:
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: linear-gradient(135deg, #0b0f19 0%, #111827 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 30px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }}
        .window-wrapper {{
            max-width: 1200px;
            width: 100%;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7), 0 0 0 1px rgba(255, 255, 255, 0.1);
        }}
        .window-wrapper svg {{
            display: block;
            width: 100%;
            height: auto;
        }}
    </style>
</head>
<body>
    <div class="window-wrapper">
        {svg_content}
    </div>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    out = Path("docs/screenshots")
    out.mkdir(parents=True, exist_ok=True)
    build_dashboard_svg(out / "01_dashboard.svg", out / "01_dashboard.html")
    build_probe_svg(out / "02_probe.svg", out / "02_probe.html")
    build_check_config_svg(out / "03_check_config.svg", out / "03_check_config.html")
    build_metrics_svg(out / "04_metrics.svg", out / "04_metrics.html")
    print("Successfully built all 4 SVGs and HTMLs in docs/screenshots/")
