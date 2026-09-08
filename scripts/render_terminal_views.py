"""Generate pixel-perfect dark terminal HTML snapshots for Sentinel."""

from __future__ import annotations

import io
import json
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


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    background: radial-gradient(circle at 50% 20%, #1e2536 0%, #0d1117 100%);
    padding: 30px;
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}}
.terminal-window {{
    background: #0a0d14;
    border-radius: 12px;
    border: 1px solid rgba(255, 255, 255, 0.12);
    box-shadow: 0 35px 70px -15px rgba(0, 0, 0, 0.9), 0 0 0 1px rgba(255, 255, 255, 0.05);
    overflow: hidden;
    width: 100%;
    max-width: 1120px;
}}
.terminal-header {{
    background: #161b26;
    padding: 12px 18px;
    display: flex;
    align-items: center;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}}
.buttons {{
    display: flex;
    gap: 8px;
}}
.btn {{
    width: 12px;
    height: 12px;
    border-radius: 50%;
    display: inline-block;
}}
.btn.red {{ background: #ff5f56; }}
.btn.yellow {{ background: #ffbd2e; }}
.btn.green {{ background: #27c93f; }}
.title {{
    flex: 1;
    text-align: center;
    color: #8b949e;
    font-size: 13px;
    font-weight: 500;
    margin-right: 48px;
}}
.terminal-body {{
    padding: 22px 26px;
    background: #0d1117;
    overflow-x: auto;
}}
pre, code {{
    font-family: Consolas, 'Cascadia Code', 'Fira Code', Menlo, monospace !important;
    font-size: 13.5px !important;
    line-height: 1.4 !important;
    color: #e6edf3 !important;
}}
{rich_styles}
</style>
</head>
<body>
<div class="terminal-window">
    <div class="terminal-header">
        <div class="buttons">
            <span class="btn red"></span>
            <span class="btn yellow"></span>
            <span class="btn green"></span>
        </div>
        <div class="title">{title}</div>
    </div>
    <div class="terminal-body">
        {content}
    </div>
</div>
</body>
</html>
"""

# Map dim or dark colors to high-contrast modern terminal colors
COLOR_REPLACEMENTS = {
    "#727272": "#94a3b8",  # readable slate grey for dim text / details
    "#543885": "#c084fc",  # bright violet instead of dark purple
    "#326e7b": "#38bdf8",  # bright sky cyan instead of dark teal
    "#58d1eb": "#38bdf8",  # vibrant sky cyan
    "#9d65ff": "#a78bfa",  # bright lavender
    "#f4005f": "#fb7185",  # vibrant rose red
    "#98e024": "#4ade80",  # bright vivid green
    "#fd971f": "#fbbf24",  # bright amber/orange
}


def extract_rich_components(full_html: str) -> tuple[str, str]:
    """Extract <style> content and <pre> content from rich export_html, boosting contrast."""
    style_start = full_html.find("<style>")
    style_end = full_html.find("</style>")
    styles = full_html[style_start + 7:style_end] if style_start != -1 and style_end != -1 else ""

    clean_styles = []
    in_body = False
    for line in styles.splitlines():
        if line.strip().startswith("body {"):
            in_body = True
            continue
        if in_body and "}" in line:
            in_body = False
            continue
        if not in_body:
            for old_col, new_col in COLOR_REPLACEMENTS.items():
                line = line.replace(old_col, new_col)
            clean_styles.append(line)

    pre_start = full_html.find("<pre")
    pre_end = full_html.rfind("</pre>")
    body_content = full_html[pre_start:pre_end + 6] if pre_start != -1 and pre_end != -1 else full_html
    return "\n".join(clean_styles), body_content


def generate_dashboard_view(dest_html: Path) -> None:
    buf = io.StringIO()
    console = Console(record=True, width=110, file=buf, force_terminal=True)
    cfg = SentinelConfig.load_yaml(Path("sites.example.yaml"))
    engine = SentinelEngine(cfg)

    api_state = TargetState(name="Production API Health", url="https://api.example.com/health")
    api_state.total_checks = 480
    api_state.successful_checks = 480
    api_state.status = TargetStatus.UP
    api_state.last_latency_ms = 45.2
    api_state.last_status_code = 200

    web_state = TargetState(name="Landing Page", url="https://example.com")
    web_state.total_checks = 240
    web_state.successful_checks = 239
    web_state.status = TargetStatus.UP
    web_state.last_latency_ms = 112.8
    web_state.last_status_code = 200

    stripe_state = TargetState(name="Stripe Webhook Listener", url="https://hooks.example.com")
    stripe_state.total_checks = 320
    stripe_state.successful_checks = 310
    stripe_state.status = TargetStatus.DOWN
    stripe_state.consecutive_failures = 3
    stripe_state.last_latency_ms = 502.4
    stripe_state.last_status_code = 503
    stripe_state.last_error_reason = "Expected status 200, got 503 Service Unavailable"
    stripe_state.down_since = datetime.now(timezone.utc)

    pg_state = TargetState(name="Primary PostgreSQL", url="tcp://db.internal:5432")
    pg_state.total_checks = 480
    pg_state.successful_checks = 480
    pg_state.status = TargetStatus.UP
    pg_state.last_latency_ms = 12.1

    redis_state = TargetState(name="Redis Cache Cluster", url="tcp://127.0.0.1:6379")
    redis_state.total_checks = 960
    redis_state.successful_checks = 960
    redis_state.status = TargetStatus.UP
    redis_state.last_latency_ms = 2.4

    engine.states = {
        "Production API Health": api_state,
        "Landing Page": web_state,
        "Stripe Webhook Listener": stripe_state,
        "Primary PostgreSQL": pg_state,
        "Redis Cache Cluster": redis_state,
    }

    dash = SentinelDashboard(engine)
    dash.start_time = time.time() - 14400.0
    dash.record_event("info", "Daemon initialized with 5 targets (3 HTTP, 2 TCP)")
    dash.record_event("info", "Prometheus metrics server active on http://0.0.0.0:9090")
    dash.record_event("alert", "OUTAGE: Stripe Webhook Listener returned 503 Service Unavailable")
    dash.record_event("info", "Telegram alert dispatched to chat -100123456789")

    console.print(dash.render())
    rich_html = console.export_html(theme=tt.MONOKAI, inline_styles=False)
    styles, content = extract_rich_components(rich_html)

    final_html = TEMPLATE.format(
        title="sentinel run --dashboard sites.yaml",
        rich_styles=styles,
        content=content,
    )
    dest_html.write_text(final_html, encoding="utf-8")


def generate_probe_view(dest_html: Path) -> None:
    buf = io.StringIO()
    console = Console(record=True, width=105, file=buf, force_terminal=True)
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

    rich_html = console.export_html(theme=tt.MONOKAI, inline_styles=False)
    styles, content = extract_rich_components(rich_html)

    final_html = TEMPLATE.format(
        title="sentinel probe sites.yaml",
        rich_styles=styles,
        content=content,
    )
    dest_html.write_text(final_html, encoding="utf-8")


def generate_check_config_view(dest_html: Path) -> None:
    buf = io.StringIO()
    console = Console(record=True, width=118, file=buf, force_terminal=True)
    console.print("[bold cyan]$ sentinel check-config sites.yaml[/bold cyan]\n")

    cfg = SentinelConfig.load_yaml(Path("sites.example.yaml"))
    import sentinel.cli
    orig_console = sentinel.cli.console
    sentinel.cli.console = console
    try:
        ConfigReportPresenter.render_summary(cfg, Path("sites.yaml"))
    finally:
        sentinel.cli.console = orig_console

    rich_html = console.export_html(theme=tt.MONOKAI, inline_styles=False)
    styles, content = extract_rich_components(rich_html)

    final_html = TEMPLATE.format(
        title="sentinel check-config sites.yaml",
        rich_styles=styles,
        content=content,
    )
    dest_html.write_text(final_html, encoding="utf-8")


def generate_metrics_view(dest_html: Path) -> None:
    buf = io.StringIO()
    console = Console(record=True, width=105, file=buf, force_terminal=True)
    console.print("[bold cyan]$ curl -s http://127.0.0.1:9090/healthz | jq .[/bold cyan]")

    states = {
        "Production API Health": TargetState(name="Production API Health", url="https://api.example.com/health"),
        "Landing Page": TargetState(name="Landing Page", url="https://example.com"),
    }
    states["Production API Health"].status = TargetStatus.UP
    states["Landing Page"].status = TargetStatus.UP

    healthz_data = HealthzExporter.format_payload(states)
    console.print(f"[green]{json.dumps(healthz_data, indent=2)}[/green]\n")

    console.print("[bold cyan]$ curl -s http://127.0.0.1:9090/metrics | grep -E '^#|sentinel_' | head -n 12[/bold cyan]")
    metrics_str = PrometheusExporter.format_metrics(states)
    for line in metrics_str.strip().split("\n")[:12]:
        if line.startswith("# HELP") or line.startswith("# TYPE"):
            console.print(f"[dim]{line}[/dim]")
        elif " 1" in line:
            console.print(f"[green]{line}[/green]")
        else:
            console.print(f"[yellow]{line}[/yellow]")

    rich_html = console.export_html(theme=tt.MONOKAI, inline_styles=False)
    styles, content = extract_rich_components(rich_html)

    final_html = TEMPLATE.format(
        title="sentinel metrics & health endpoints (9090)",
        rich_styles=styles,
        content=content,
    )
    dest_html.write_text(final_html, encoding="utf-8")


if __name__ == "__main__":
    out = Path("docs/screenshots")
    out.mkdir(parents=True, exist_ok=True)
    generate_dashboard_view(out / "01_dashboard.html")
    generate_probe_view(out / "02_probe.html")
    generate_check_config_view(out / "03_check_config.html")
    generate_metrics_view(out / "04_metrics.html")
    print("Generated all 4 styled HTML screenshots in docs/screenshots/")
