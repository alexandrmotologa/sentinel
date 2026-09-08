"""Unit tests for the terminal user interface dashboard."""

from __future__ import annotations

from rich.layout import Layout

from sentinel.config import GlobalConfig, SentinelConfig, TargetConfig, TCPTargetConfig
from sentinel.dashboard import SentinelDashboard, _get_latency_bar
from sentinel.engine import SentinelEngine
from sentinel.state import TargetStatus


def test_get_latency_bar():
    green_bar = _get_latency_bar(50.0)
    assert "green" in green_bar
    assert "50ms" in green_bar

    yellow_bar = _get_latency_bar(350.0)
    assert "yellow" in yellow_bar
    assert "350ms" in yellow_bar

    red_bar = _get_latency_bar(800.0)
    assert "red" in red_bar
    assert "800ms" in red_bar


def test_dashboard_render_layout():
    config = SentinelConfig(
        global_config=GlobalConfig(),
        targets=[TargetConfig(name="web", url="https://example.com")],
        tcp_targets=[TCPTargetConfig(name="db", host="127.0.0.1", port=5432)],
    )
    engine = SentinelEngine(config)
    dashboard = SentinelDashboard(engine)

    # Set states
    web_state = engine.get_state("web")
    assert web_state is not None
    web_state.status = TargetStatus.UP
    web_state.last_latency_ms = 42.0

    db_state = engine.get_state("db")
    assert db_state is not None
    db_state.status = TargetStatus.DOWN
    db_state.last_error_reason = "Connection refused"

    dashboard.record_event("outage", "db unreachable")
    dashboard.record_event("recovery", "web restored")

    layout = dashboard.render()
    assert isinstance(layout, Layout)
    assert "header" in [child.name for child in layout.children]
    assert "body" in [child.name for child in layout.children]
    assert "footer" in [child.name for child in layout.children]
