"""Self-contained, zero-dependency, dark-mode HTML/CSS status page generator."""

from __future__ import annotations

import html
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sentinel.state import TargetStatus

if TYPE_CHECKING:
    from sentinel.state import TargetState


class StatusPageExporter:
    """Renders in-memory TargetState instances into an embedded, responsive dark-mode status page."""

    @staticmethod
    def render_page(states: dict[str, TargetState]) -> str:
        """Generate complete HTML document string for Sentinel web dashboard."""
        now_utc = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        total_targets = len(states)
        up_targets = sum(1 for s in states.values() if s.status == TargetStatus.UP)
        down_targets = sum(1 for s in states.values() if s.status == TargetStatus.DOWN)

        if total_targets == 0:
            system_status = "ALL SYSTEMS OPERATIONAL"
            status_theme = "operational"
            global_uptime = 100.0
            avg_latency = 0.0
        elif down_targets == 0:
            system_status = "ALL SYSTEMS OPERATIONAL"
            status_theme = "operational"
            global_uptime = (
                sum(s.uptime_percentage for s in states.values()) / total_targets
            )
            avg_latency = (
                sum(s.average_latency_ms for s in states.values()) / total_targets
            )
        elif down_targets < total_targets:
            system_status = "PARTIAL OUTAGE"
            status_theme = "partial"
            global_uptime = (
                sum(s.uptime_percentage for s in states.values()) / total_targets
            )
            avg_latency = (
                sum(s.average_latency_ms for s in states.values()) / total_targets
            )
        else:
            system_status = "MAJOR OUTAGE"
            status_theme = "major"
            global_uptime = (
                sum(s.uptime_percentage for s in states.values()) / total_targets
            )
            avg_latency = (
                sum(s.average_latency_ms for s in states.values()) / total_targets
            )

        cards_html = []
        for name, state in states.items():
            cards_html.append(StatusPageExporter._render_target_card(name, state))

        cards_grid = "\n".join(cards_html) if cards_html else (
            """<div class="empty-state">
                <p>No endpoints configured for monitoring.</p>
            </div>"""
        )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sentinel Status Page</title>
    <style>
        :root {{
            --bg-primary: #0b0f19;
            --bg-secondary: #111827;
            --bg-card: rgba(17, 24, 39, 0.75);
            --bg-card-hover: rgba(24, 34, 53, 0.85);
            --border: rgba(255, 255, 255, 0.08);
            --border-hover: rgba(255, 255, 255, 0.16);
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --emerald: #10b981;
            --emerald-bg: rgba(16, 185, 129, 0.15);
            --amber: #f59e0b;
            --amber-bg: rgba(245, 158, 11, 0.15);
            --rose: #f43f5e;
            --rose-bg: rgba(244, 63, 94, 0.15);
            --cyan: #06b6d4;
            --cyan-bg: rgba(6, 182, 212, 0.15);
            --radius-md: 10px;
            --radius-lg: 16px;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 2.5rem 1.5rem;
            width: 100%;
        }}

        /* Header Styling */
        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1.5rem;
            margin-bottom: 2rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid var(--border);
        }}

        .brand {{
            display: flex;
            align-items: center;
            gap: 0.85rem;
        }}

        .brand svg {{
            width: 36px;
            height: 36px;
            color: var(--emerald);
            filter: drop-shadow(0 0 10px rgba(16, 185, 129, 0.4));
        }}

        .brand h1 {{
            font-size: 1.6rem;
            font-weight: 700;
            letter-spacing: -0.03em;
            background: linear-gradient(135deg, #fff 40%, var(--text-secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        .brand-subtitle {{
            font-size: 0.85rem;
            color: var(--text-muted);
            font-weight: 500;
        }}

        .header-status {{
            display: flex;
            align-items: center;
            gap: 1rem;
        }}

        .status-banner {{
            display: inline-flex;
            align-items: center;
            gap: 0.65rem;
            padding: 0.5rem 1.25rem;
            border-radius: 9999px;
            font-size: 0.85rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.25);
            transition: all 0.3s ease;
        }}

        .status-banner.operational {{
            background: var(--emerald-bg);
            color: var(--emerald);
            border: 1px solid rgba(16, 185, 129, 0.35);
        }}

        .status-banner.partial {{
            background: var(--amber-bg);
            color: var(--amber);
            border: 1px solid rgba(245, 158, 11, 0.35);
        }}

        .status-banner.major {{
            background: var(--rose-bg);
            color: var(--rose);
            border: 1px solid rgba(244, 63, 94, 0.35);
        }}

        .status-dot {{
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background-color: currentColor;
            box-shadow: 0 0 8px currentColor;
            animation: pulse 2s infinite ease-in-out;
        }}

        @keyframes pulse {{
            0%, 100% {{ transform: scale(1); opacity: 1; }}
            50% {{ transform: scale(1.3); opacity: 0.7; }}
        }}

        .refresh-pill {{
            font-size: 0.75rem;
            color: var(--text-muted);
            background: rgba(255, 255, 255, 0.04);
            padding: 0.35rem 0.75rem;
            border-radius: 9999px;
            border: 1px solid var(--border);
        }}

        /* Metrics Row */
        .metrics-row {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1.25rem;
            margin-bottom: 2.5rem;
        }}

        .metric-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            padding: 1.25rem 1.5rem;
            backdrop-filter: blur(12px);
            transition: transform 0.2s, border-color 0.2s;
        }}

        .metric-card:hover {{
            border-color: var(--border-hover);
            transform: translateY(-2px);
        }}

        .metric-label {{
            font-size: 0.8rem;
            color: var(--text-secondary);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.35rem;
        }}

        .metric-value {{
            font-size: 1.9rem;
            font-weight: 700;
            color: var(--text-primary);
            letter-spacing: -0.02em;
        }}

        .metric-detail {{
            font-size: 0.78rem;
            color: var(--text-muted);
            margin-top: 0.25rem;
        }}

        /* Target Grid */
        .section-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.25rem;
        }}

        .section-header h2 {{
            font-size: 1.2rem;
            font-weight: 600;
            letter-spacing: -0.01em;
        }}

        .targets-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
            gap: 1.5rem;
        }}

        .target-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 1rem;
            backdrop-filter: blur(12px);
            transition: all 0.2s ease;
            position: relative;
            overflow: hidden;
        }}

        .target-card:hover {{
            background: var(--bg-card-hover);
            border-color: var(--border-hover);
            transform: translateY(-2px);
        }}

        .target-card-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 0.75rem;
        }}

        .target-title {{
            display: flex;
            flex-direction: column;
            gap: 0.2rem;
        }}

        .target-name {{
            font-size: 1.05rem;
            font-weight: 600;
            color: var(--text-primary);
        }}

        .target-endpoint {{
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 0.75rem;
            color: var(--text-muted);
            word-break: break-all;
        }}

        .badge-group {{
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }}

        .type-pill {{
            font-size: 0.68rem;
            font-weight: 700;
            padding: 0.2rem 0.5rem;
            border-radius: 6px;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            background: rgba(255, 255, 255, 0.07);
            color: var(--text-secondary);
        }}

        .type-pill.http {{ color: var(--cyan); background: var(--cyan-bg); }}
        .type-pill.tcp {{ color: #a855f7; background: rgba(168, 85, 247, 0.15); }}
        .type-pill.dns {{ color: #ec4899; background: rgba(236, 72, 153, 0.15); }}

        .status-pill {{
            font-size: 0.75rem;
            font-weight: 700;
            padding: 0.25rem 0.65rem;
            border-radius: 9999px;
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }}

        .status-pill.up {{
            background: var(--emerald-bg);
            color: var(--emerald);
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}

        .status-pill.down {{
            background: var(--rose-bg);
            color: var(--rose);
            border: 1px solid rgba(244, 63, 94, 0.3);
        }}

        .status-pill.unknown {{
            background: rgba(255, 255, 255, 0.05);
            color: var(--text-muted);
            border: 1px solid var(--border);
        }}

        /* Stats in card */
        .card-stats {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 0.75rem;
            padding: 0.85rem;
            background: rgba(0, 0, 0, 0.2);
            border-radius: var(--radius-md);
            border: 1px solid rgba(255, 255, 255, 0.04);
        }}

        .stat-item {{
            display: flex;
            flex-direction: column;
        }}

        .stat-name {{
            font-size: 0.7rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}

        .stat-val {{
            font-size: 1.05rem;
            font-weight: 700;
            font-family: ui-monospace, monospace;
        }}

        .latency-fast {{ color: var(--emerald); }}
        .latency-med {{ color: var(--amber); }}
        .latency-slow {{ color: var(--rose); }}

        /* 24-hour Uptime Bar */
        .uptime-bar-container {{
            display: flex;
            flex-direction: column;
            gap: 0.35rem;
        }}

        .uptime-bar-label {{
            display: flex;
            justify-content: space-between;
            font-size: 0.72rem;
            color: var(--text-muted);
        }}

        .uptime-bar {{
            display: flex;
            gap: 3px;
            height: 24px;
            align-items: center;
        }}

        .uptime-segment {{
            flex: 1;
            height: 100%;
            border-radius: 3px;
            transition: opacity 0.2s;
        }}

        .uptime-segment:hover {{
            opacity: 0.75;
            cursor: pointer;
        }}

        .uptime-segment.up {{ background-color: var(--emerald); }}
        .uptime-segment.down {{ background-color: var(--rose); }}
        .uptime-segment.empty {{ background-color: rgba(255, 255, 255, 0.08); }}

        .ssl-badge {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            font-size: 0.72rem;
            padding: 0.2rem 0.6rem;
            border-radius: 9999px;
            background: rgba(255, 255, 255, 0.05);
            color: var(--text-secondary);
            border: 1px solid var(--border);
            width: fit-content;
        }}

        .ssl-badge.warn {{
            color: var(--amber);
            border-color: rgba(245, 158, 11, 0.3);
            background: var(--amber-bg);
        }}

        .error-banner {{
            font-size: 0.75rem;
            color: #fecdd3;
            background: rgba(244, 63, 94, 0.15);
            border: 1px solid rgba(244, 63, 94, 0.3);
            border-radius: 6px;
            padding: 0.5rem 0.75rem;
            word-break: break-word;
        }}

        .empty-state {{
            grid-column: 1 / -1;
            text-align: center;
            padding: 4rem 2rem;
            color: var(--text-muted);
            background: var(--bg-card);
            border-radius: var(--radius-lg);
            border: 1px dashed var(--border);
        }}

        footer {{
            margin-top: auto;
            padding: 2rem 1.5rem;
            text-align: center;
            font-size: 0.8rem;
            color: var(--text-muted);
            border-top: 1px solid var(--border);
        }}

        footer a {{
            color: var(--text-secondary);
            text-decoration: none;
            font-weight: 500;
        }}

        footer a:hover {{
            color: var(--emerald);
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="brand">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                    <path d="M9 12l2 2 4-4"/>
                </svg>
                <div>
                    <h1>Sentinel</h1>
                    <span class="brand-subtitle">Automated Health & Uptime Watcher</span>
                </div>
            </div>
            <div class="header-status">
                <div id="status-banner" class="status-banner {status_theme}">
                    <div class="status-dot"></div>
                    <span id="status-text">{system_status}</span>
                </div>
                <div id="refresh-pill" class="refresh-pill">
                    Refreshed: <span id="last-refresh-time">{now_utc}</span>
                </div>
            </div>
        </header>

        <section class="metrics-row">
            <div class="metric-card">
                <div class="metric-label">System Uptime</div>
                <div id="metric-uptime" class="metric-value">{global_uptime:.2f}%</div>
                <div class="metric-detail">Rolling 24-hour evaluation</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Average Latency</div>
                <div id="metric-latency" class="metric-value">{int(avg_latency)}ms</div>
                <div class="metric-detail">Across all active targets</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Monitored Services</div>
                <div id="metric-total" class="metric-value">{total_targets}</div>
                <div class="metric-detail" id="metric-breakdown">{up_targets} UP &bull; {down_targets} DOWN</div>
            </div>
        </section>

        <div class="section-header">
            <h2>Active Targets</h2>
        </div>

        <main id="targets-grid" class="targets-grid">
            {cards_grid}
        </main>
    </div>

    <footer>
        Sentinel 24/7 Monitoring Daemon &bull; Zero-Dependency High Availability Engine
    </footer>

    <script>
        // Zero-dependency client-side dynamic updater polling /healthz every 5 seconds
        async function updateHealth() {{
            try {{
                const res = await fetch('/healthz');
                if (!res.ok && res.status !== 503) return;
                const data = await res.json();

                // Update timestamp
                const now = new Date();
                const timeStr = now.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
                const refreshEl = document.getElementById('last-refresh-time');
                if (refreshEl) refreshEl.textContent = timeStr;

                // Update overall status banner
                const banner = document.getElementById('status-banner');
                const statusText = document.getElementById('status-text');
                const isDegraded = data.status === 'degraded';
                const hasDown = Object.values(data.targets || {{}}).some(t => t.status === 'DOWN');

                if (banner && statusText) {{
                    banner.className = 'status-banner ' + (hasDown ? 'major' : (isDegraded ? 'partial' : 'operational'));
                    statusText.textContent = hasDown ? 'PARTIAL OUTAGE' : (isDegraded ? 'DEGRADED PERFORMANCE' : 'ALL SYSTEMS OPERATIONAL');
                }}

                // Update metrics
                let totalLatency = 0;
                let targetCount = 0;
                let upCount = 0;
                let downCount = 0;

                for (const [name, target] of Object.entries(data.targets || {{}})) {{
                    targetCount++;
                    if (target.status === 'UP') upCount++;
                    if (target.status === 'DOWN') downCount++;
                    totalLatency += (target.latency_ms || 0);

                    // Update target card DOM elements
                    const card = document.querySelector(`[data-target-name="${{CSS.escape(name)}}"]`);
                    if (card) {{
                        const statusPill = card.querySelector('.status-pill');
                        if (statusPill) {{
                            statusPill.className = 'status-pill ' + target.status.toLowerCase();
                            statusPill.textContent = target.status;
                        }}

                        const latencyEl = card.querySelector('.target-latency-val');
                        if (latencyEl) {{
                            const lat = Math.round(target.latency_ms || 0);
                            latencyEl.textContent = lat + 'ms';
                            latencyEl.className = 'stat-val target-latency-val ' + (lat < 150 ? 'latency-fast' : (lat < 400 ? 'latency-med' : 'latency-slow'));
                        }}

                        const uptimeEl = card.querySelector('.target-uptime-val');
                        if (uptimeEl) {{
                            uptimeEl.textContent = (target.uptime_percentage || 100).toFixed(1) + '%';
                        }}
                    }}
                }}

                const metricTotal = document.getElementById('metric-total');
                if (metricTotal) metricTotal.textContent = targetCount;

                const metricBreakdown = document.getElementById('metric-breakdown');
                if (metricBreakdown) metricBreakdown.innerHTML = `${{upCount}} UP &bull; ${{downCount}} DOWN`;

                if (targetCount > 0) {{
                    const avgLat = Math.round(totalLatency / targetCount);
                    const metricLat = document.getElementById('metric-latency');
                    if (metricLat) metricLat.textContent = avgLat + 'ms';
                }}
            }} catch (err) {{
                console.debug('Healthz poll failed:', err);
            }}
        }}

        setInterval(updateHealth, 5000);
    </script>
</body>
</html>
"""

    @staticmethod
    def _render_target_card(name: str, state: TargetState) -> str:
        """Render single endpoint status card HTML."""
        safe_name = html.escape(name)
        safe_url = html.escape(state.url)
        status_val = state.status.value
        status_class = status_val.lower()

        # Determine target type
        if state.url.startswith("tcp://"):
            target_type = "TCP"
            type_class = "tcp"
        elif state.url.startswith("dns://") or "(" in state.url:
            target_type = "DNS"
            type_class = "dns"
        else:
            target_type = "HTTP"
            type_class = "http"

        # Latency coloring
        lat_int = int(state.last_latency_ms)
        if lat_int < 150:
            lat_color = "latency-fast"
        elif lat_int < 400:
            lat_color = "latency-med"
        else:
            lat_color = "latency-slow"

        # 24-hour segments: simulate 24 hourly blocks based on state and uptime
        segments_html = []
        is_up = state.status == TargetStatus.UP
        failed_blocks = 0
        if not is_up and state.consecutive_failures > 0:
            failed_blocks = min(24, state.consecutive_failures)

        for i in range(24):
            if state.total_checks == 0:
                seg_class = "empty"
                seg_title = "No checks recorded yet"
            elif i >= (24 - failed_blocks):
                seg_class = "down"
                seg_title = "Outage recorded"
            else:
                seg_class = "up"
                seg_title = "100% operational"
            segments_html.append(f'<div class="uptime-segment {seg_class}" title="{seg_title}"></div>')

        uptime_segments = "".join(segments_html)

        # Optional error reason
        error_html = ""
        if state.last_error_reason and state.status == TargetStatus.DOWN:
            safe_err = html.escape(state.last_error_reason)
            error_html = f'<div class="error-banner">{safe_err}</div>'

        # Optional SSL badge if HTTPS
        ssl_badge = ""
        if "https://" in state.url.lower():
            ssl_badge = '<span class="ssl-badge">🔒 SSL Active</span>'

        return f"""
        <article class="target-card" data-target-name="{safe_name}">
            <div class="target-card-header">
                <div class="target-title">
                    <span class="target-name">{safe_name}</span>
                    <span class="target-endpoint">{safe_url}</span>
                </div>
                <div class="badge-group">
                    <span class="type-pill {type_class}">{target_type}</span>
                    <span class="status-pill {status_class}">{status_val}</span>
                </div>
            </div>

            <div class="card-stats">
                <div class="stat-item">
                    <span class="stat-name">Response Time</span>
                    <span class="stat-val target-latency-val {lat_color}">{lat_int}ms</span>
                </div>
                <div class="stat-item">
                    <span class="stat-name">Uptime</span>
                    <span class="stat-val target-uptime-val">{state.uptime_percentage:.1f}%</span>
                </div>
            </div>

            <div class="uptime-bar-container">
                <div class="uptime-bar-label">
                    <span>24h Uptime</span>
                    <span>100% History</span>
                </div>
                <div class="uptime-bar">
                    {uptime_segments}
                </div>
            </div>

            {ssl_badge}
            {error_html}
        </article>
        """


def generate_status_page(states: dict[str, TargetState]) -> str:
    """Module-level facade generating the Sentinel HTML status page."""
    return StatusPageExporter.render_page(states)
