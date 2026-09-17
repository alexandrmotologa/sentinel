"""Self-contained, zero-dependency, dark-mode HTML/CSS status page generator with branding and incident timeline."""

from __future__ import annotations

import html
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sentinel.config import StatusPageConfig
from sentinel.state import TargetStatus, format_duration

if TYPE_CHECKING:
    from sentinel.state import TargetState


class _RenderPageCallable:
    """Descriptor allowing render_page to be called both on instance and class."""

    def __get__(self, instance: Any, owner: type[Any] | None = None) -> Any:
        if instance is not None:
            def _instance_caller(
                states: dict[str, TargetState] | list[TargetState],
                config: StatusPageConfig | None = None,
                incidents: list[Any] | None = None,
                active_mutes: list[str] | set[str] | None = None,
                recent_incidents: list[Any] | None = None,
                muted_targets: set[str] | list[str] | None = None,
            ) -> str:
                cfg = config if config is not None else instance.config
                return owner._render_page_impl(
                    states=states,
                    config=cfg,
                    incidents=incidents,
                    active_mutes=active_mutes,
                    recent_incidents=recent_incidents,
                    muted_targets=muted_targets,
                )
            return _instance_caller

        def _class_caller(
            states: dict[str, TargetState] | list[TargetState],
            config: StatusPageConfig | None = None,
            incidents: list[Any] | None = None,
            active_mutes: list[str] | set[str] | None = None,
            recent_incidents: list[Any] | None = None,
            muted_targets: set[str] | list[str] | None = None,
        ) -> str:
            assert owner is not None
            return owner._render_page_impl(
                states=states,
                config=config,
                incidents=incidents,
                active_mutes=active_mutes,
                recent_incidents=recent_incidents,
                muted_targets=muted_targets,
            )
        return _class_caller


class StatusPageExporter:
    """Renders in-memory TargetState instances into an embedded, responsive dark-mode status page."""

    render_page = _RenderPageCallable()
    render = _RenderPageCallable()

    def __init__(self, config: StatusPageConfig | None = None) -> None:
        self.config = config

    @classmethod
    def _render_page_impl(
        cls,
        states: dict[str, TargetState] | list[TargetState],
        config: StatusPageConfig | None = None,
        incidents: list[Any] | None = None,
        active_mutes: list[str] | set[str] | None = None,
        recent_incidents: list[Any] | None = None,
        muted_targets: set[str] | list[str] | None = None,
    ) -> str:
        if isinstance(states, list):
            states = {s.name: s for s in states}

        effective_incidents = incidents if incidents is not None else recent_incidents
        mutes_set = set(active_mutes or []) | set(muted_targets or [])
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

        # Cards grid
        cards_html = []
        for name, state in states.items():
            cards_html.append(StatusPageExporter._render_target_card(name, state, is_muted=(name in mutes_set)))

        cards_grid = "\n".join(cards_html) if cards_html else (
            """<div class="empty-state">
                <p>No endpoints configured for monitoring.</p>
            </div>"""
        )

        # Branding
        cfg = config or StatusPageConfig()
        page_title = html.escape(cfg.title or "Sentinel Status Page")
        company = html.escape(cfg.company_name) if cfg.company_name else ""
        brand_subtitle = (
            f"Automated Health &amp; Uptime Watcher for {company}"
            if company
            else "Automated Health &amp; Uptime Watcher"
        )

        if cfg.logo_url:
            logo_html = f'<img src="{html.escape(cfg.logo_url)}" alt="Logo" class="custom-brand-logo">'
        else:
            logo_html = """
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                <path d="M9 12l2 2 4-4"/>
            </svg>
            """

        # Announcement Banner
        announcement_html = ""
        banner_text = getattr(cfg, "announcement_banner", None) or cfg.announcement
        if banner_text:
            ann_type = cfg.announcement_type or "info"
            ann_icon = "ℹ️" if ann_type == "info" else ("⚠️" if ann_type == "warning" else "🚨")
            announcement_html = f"""
            <div class="announcement-banner banner-{html.escape(ann_type)} {html.escape(ann_type)}">
                <span class="announcement-icon">{ann_icon}</span>
                <span class="announcement-text">{html.escape(banner_text)}</span>
            </div>
            """

        # Incidents Section
        incidents_html = StatusPageExporter._render_incidents_section(effective_incidents)

        # Custom CSS injection
        custom_css_html = f"<style>{cfg.custom_css}</style>" if cfg.custom_css else ""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title}</title>
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
            --orange: #f97316;
            --orange-bg: rgba(249, 115, 22, 0.15);
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

        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid var(--border);
            flex-wrap: wrap;
            gap: 1rem;
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
        }}

        .custom-brand-logo {{
            width: 40px;
            height: 40px;
            object-fit: contain;
            border-radius: 8px;
        }}

        .brand h1 {{
            font-size: 1.5rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            color: var(--text-primary);
        }}

        .brand-subtitle {{
            font-size: 0.82rem;
            color: var(--text-muted);
            display: block;
        }}

        .header-status {{
            display: flex;
            align-items: center;
            gap: 1rem;
        }}

        .status-banner {{
            display: inline-flex;
            align-items: center;
            gap: 0.6rem;
            padding: 0.5rem 1.1rem;
            border-radius: 9999px;
            font-weight: 600;
            font-size: 0.88rem;
            letter-spacing: 0.02em;
        }}

        .status-banner.operational {{
            background: var(--emerald-bg);
            color: var(--emerald);
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}

        .status-banner.partial {{
            background: var(--amber-bg);
            color: var(--amber);
            border: 1px solid rgba(245, 158, 11, 0.3);
        }}

        .status-banner.major {{
            background: var(--rose-bg);
            color: var(--rose);
            border: 1px solid rgba(244, 63, 94, 0.3);
        }}

        .status-dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: currentColor;
            box-shadow: 0 0 8px currentColor;
        }}

        .refresh-pill {{
            font-size: 0.75rem;
            color: var(--text-muted);
            background: var(--bg-secondary);
            padding: 0.4rem 0.8rem;
            border-radius: 6px;
            border: 1px solid var(--border);
        }}

        /* Announcement Banner */
        .announcement-banner {{
            border-radius: var(--radius-md);
            padding: 0.9rem 1.25rem;
            margin-bottom: 2rem;
            display: flex;
            align-items: center;
            gap: 0.85rem;
            font-size: 0.92rem;
            line-height: 1.4;
        }}

        .announcement-banner.info {{
            background: rgba(6, 182, 212, 0.12);
            border: 1px solid rgba(6, 182, 212, 0.35);
            color: #38bdf8;
        }}

        .announcement-banner.warning {{
            background: rgba(245, 158, 11, 0.12);
            border: 1px solid rgba(245, 158, 11, 0.35);
            color: #fbbf24;
        }}

        .announcement-banner.outage {{
            background: rgba(244, 63, 94, 0.12);
            border: 1px solid rgba(244, 63, 94, 0.35);
            color: #fb7185;
        }}

        .announcement-icon {{
            font-size: 1.2rem;
        }}

        /* High-level metrics */
        .metrics-row {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 1.25rem;
            margin-bottom: 2.5rem;
        }}

        .metric-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 1.25rem;
            backdrop-filter: blur(10px);
        }}

        .metric-label {{
            font-size: 0.8rem;
            text-transform: uppercase;
            color: var(--text-muted);
            font-weight: 600;
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
            flex-wrap: wrap;
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
        .type-pill.ping {{ color: var(--orange); background: var(--orange-bg); }}
        .type-pill.muted {{ color: var(--amber); background: var(--amber-bg); }}

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

        .card-stats {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0.75rem;
            background: rgba(0, 0, 0, 0.2);
            padding: 0.75rem 1rem;
            border-radius: var(--radius-md);
            border: 1px solid rgba(255, 255, 255, 0.04);
        }}

        .stat-item {{
            display: flex;
            flex-direction: column;
            gap: 0.15rem;
        }}

        .stat-name {{
            font-size: 0.72rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}

        .stat-val {{
            font-size: 1.15rem;
            font-weight: 700;
            color: var(--text-primary);
            font-feature-settings: "tnum";
        }}

        .latency-fast {{ color: var(--emerald); }}
        .latency-med {{ color: var(--amber); }}
        .latency-slow {{ color: var(--rose); }}

        /* 24-hour visual bar */
        .uptime-bar-container {{
            display: flex;
            flex-direction: column;
            gap: 0.4rem;
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
            height: 28px;
            width: 100%;
        }}

        .uptime-segment {{
            flex: 1;
            border-radius: 3px;
            background: var(--emerald);
            opacity: 0.9;
            transition: opacity 0.2s ease, transform 0.2s ease;
        }}

        .uptime-segment:hover {{
            opacity: 1;
            transform: scaleY(1.15);
        }}

        .uptime-segment.down {{
            background: var(--rose);
        }}

        .uptime-segment.empty {{
            background: rgba(255, 255, 255, 0.06);
        }}

        .ssl-badge {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            font-size: 0.72rem;
            color: var(--text-muted);
            margin-top: -0.25rem;
        }}

        .error-banner {{
            background: var(--rose-bg);
            border: 1px solid rgba(244, 63, 94, 0.25);
            border-radius: 6px;
            padding: 0.5rem 0.75rem;
            font-size: 0.75rem;
            color: var(--rose);
            line-height: 1.4;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        }}

        /* Incidents Section */
        .incidents-section {{
            margin-top: 3.5rem;
        }}

        .incidents-list {{
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }}

        .incident-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 1.25rem 1.5rem;
            backdrop-filter: blur(10px);
        }}

        .incident-card.ongoing {{
            border-left: 4px solid var(--rose);
        }}

        .incident-card.resolved {{
            border-left: 4px solid var(--emerald);
        }}

        .incident-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
            flex-wrap: wrap;
            gap: 0.5rem;
        }}

        .incident-title-group {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }}

        .incident-target {{
            font-weight: 600;
            font-size: 1rem;
            color: var(--text-primary);
        }}

        .incident-status-pill {{
            font-size: 0.7rem;
            font-weight: 700;
            padding: 0.15rem 0.55rem;
            border-radius: 9999px;
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }}

        .incident-status-pill.ongoing {{
            background: var(--rose-bg);
            color: var(--rose);
            border: 1px solid rgba(244, 63, 94, 0.3);
        }}

        .incident-status-pill.resolved {{
            background: var(--emerald-bg);
            color: var(--emerald);
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}

        .incident-time {{
            font-size: 0.78rem;
            color: var(--text-muted);
        }}

        .incident-body p {{
            font-size: 0.85rem;
            color: var(--text-secondary);
            margin-bottom: 0.5rem;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        }}

        .incident-meta {{
            font-size: 0.78rem;
            color: var(--text-muted);
            display: flex;
            gap: 1.5rem;
        }}

        .no-incidents {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 1.5rem;
            text-align: center;
            color: var(--text-secondary);
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.6rem;
            font-size: 0.9rem;
        }}

        .empty-state {{
            grid-column: 1 / -1;
            text-align: center;
            padding: 3rem 1rem;
            background: var(--bg-card);
            border: 1px dashed var(--border);
            border-radius: var(--radius-lg);
            color: var(--text-muted);
        }}

        footer {{
            margin-top: auto;
            text-align: center;
            padding: 2.5rem 1.5rem;
            border-top: 1px solid var(--border);
            font-size: 0.8rem;
            color: var(--text-muted);
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
    {custom_css_html}
</head>
<body>
    <div class="container">
        <header>
            <div class="brand">
                {logo_html}
                <div>
                    <h1>{page_title}</h1>
                    <span class="brand-subtitle">{brand_subtitle}</span>
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

        {announcement_html}

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

        {incidents_html}
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
                const totalEl = document.getElementById('metric-total');
                const breakdownEl = document.getElementById('metric-breakdown');

                if (totalEl) totalEl.textContent = data.total_targets;
                if (breakdownEl) {{
                    const down = data.total_targets - data.healthy_targets;
                    breakdownEl.innerHTML = `${{data.healthy_targets}} UP &bull; ${{down}} DOWN`;
                }}

                if (data.healthy_targets === data.total_targets) {{
                    if (banner) banner.className = 'status-banner operational';
                    if (statusText) statusText.textContent = 'ALL SYSTEMS OPERATIONAL';
                }} else if (data.healthy_targets > 0) {{
                    if (banner) banner.className = 'status-banner partial';
                    if (statusText) statusText.textContent = 'PARTIAL OUTAGE';
                }} else {{
                    if (banner) banner.className = 'status-banner major';
                    if (statusText) statusText.textContent = 'MAJOR OUTAGE';
                }}

                // Update target card pills
                if (data.targets) {{
                    for (const [name, target] of Object.entries(data.targets)) {{
                        const card = document.querySelector(`[data-target-name="${{name}}"]`);
                        if (!card) continue;

                        const statusPill = card.querySelector('.status-pill');
                        if (statusPill) {{
                            statusPill.textContent = target.status;
                            statusPill.className = `status-pill ${{target.status.toLowerCase()}}`;
                        }}

                        const latencyVal = card.querySelector('.target-latency-val');
                        if (latencyVal) {{
                            const lat = Math.round(target.latency_ms);
                            latencyVal.textContent = `${{lat}}ms`;
                            let latClass = 'latency-fast';
                            if (lat >= 400) latClass = 'latency-slow';
                            else if (lat >= 150) latClass = 'latency-med';
                            latencyVal.className = `stat-val target-latency-val ${{latClass}}`;
                        }}

                        const uptimeVal = card.querySelector('.target-uptime-val');
                        if (uptimeVal) {{
                            uptimeVal.textContent = `${{target.uptime_percentage.toFixed(1)}}%`;
                        }}
                    }}
                }}
            }} catch (e) {{
                // Silent fail for polling errors
            }}
        }}

        setInterval(updateHealth, 5000);
    </script>
</body>
</html>
"""

    @staticmethod
    def _render_incidents_section(incidents: list[Any] | None) -> str:
        """Render Past Incidents list or empty confirmation block."""
        if not incidents:
            return """
            <section class="incidents-section">
                <div class="section-header">
                    <h2>Past Incidents (Last 7 Days)</h2>
                </div>
                <div class="no-incidents">
                    <span>✅</span>
                    <span>All systems operational &bull; No incidents recorded in the past 7 days</span>
                </div>
            </section>
            """

        items_html = []
        for inc in incidents:
            if hasattr(inc, "target_name"):
                target_name = inc.target_name
                status_raw = str(inc.status or "resolved").lower()
                if getattr(inc, "resolved_at", None) is not None:
                    status_raw = "resolved"
                started_raw = (
                    inc.started_at.strftime("%Y-%m-%d %H:%M:%S")
                    if getattr(inc, "started_at", None)
                    else ""
                )
                duration_val = inc.duration_seconds
                error_raw = inc.error_reason
            else:
                target_name = inc.get("target_name", "Unknown Target")
                status_raw = str(inc.get("status", "resolved")).lower()
                if inc.get("resolved_at") is not None:
                    status_raw = "resolved"
                started_raw = str(inc.get("started_at", ""))[:19].replace("T", " ")
                duration_val = inc.get("duration_seconds")
                error_raw = inc.get("error_reason")

            safe_name = html.escape(str(target_name or "Unknown Target"))
            safe_status = "Ongoing" if status_raw == "ongoing" else "Resolved"
            status_class = "ongoing" if status_raw == "ongoing" else "resolved"
            started_at = (
                started_raw + " UTC"
                if not started_raw.endswith("UTC")
                else started_raw
            )
            duration = format_duration(float(duration_val or 0.0))
            reason = html.escape(str(error_raw or "Service health check failure"))

            items_html.append(
                f"""
                <div class="incident-card {status_class}">
                    <div class="incident-header">
                        <div class="incident-title-group">
                            <span class="incident-target">{safe_name}</span>
                            <span class="incident-status-pill {status_class}">{safe_status}</span>
                        </div>
                        <span class="incident-time">{started_at}</span>
                    </div>
                    <div class="incident-body">
                        <p>{reason}</p>
                        <div class="incident-meta">
                            <span>Downtime Duration: <strong>{duration}</strong></span>
                        </div>
                    </div>
                </div>
                """
            )

        return f"""
        <section class="incidents-section">
            <div class="section-header">
                <h2>Past Incidents (Last 7 Days)</h2>
            </div>
            <div class="incidents-list">
                {"".join(items_html)}
            </div>
        </section>
        """

    @staticmethod
    def _render_target_card(name: str, state: TargetState, is_muted: bool = False) -> str:
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
        elif state.url.startswith("ping://"):
            target_type = "PING"
            type_class = "ping"
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

        # 24-hour segments
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

        # Muted badge and notice
        muted_badge = '<span class="type-pill muted">MAINTENANCE</span>' if is_muted else ""
        maintenance_html = '<div class="maintenance-notice">⚠️ Under scheduled maintenance</div>' if is_muted else ""

        return f"""
        <article class="target-card" data-target-name="{safe_name}">
            <div class="target-card-header">
                <div class="target-title">
                    <span class="target-name">{safe_name}</span>
                    <span class="target-endpoint">{safe_url}</span>
                </div>
                <div class="badge-group">
                    {muted_badge}
                    <span class="type-pill {type_class}">{target_type}</span>
                    <span class="status-pill {status_class}">{status_val}</span>
                </div>
            </div>

            <div class="target-stats">
                <div class="stat-item">
                    <span class="stat-name">Response</span>
                    <span class="stat-val {lat_color}">{lat_int} ms</span>
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
            {maintenance_html}
        </article>
        """


def generate_status_page(
    states: dict[str, TargetState],
    config: StatusPageConfig | None = None,
    incidents: list[dict[str, Any]] | None = None,
    active_mutes: list[str] | None = None,
) -> str:
    """Module-level facade generating the Sentinel HTML status page."""
    return StatusPageExporter.render_page(
        states, config=config, incidents=incidents, active_mutes=active_mutes
    )
