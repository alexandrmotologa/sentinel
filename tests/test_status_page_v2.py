"""Tests for Web Status Page branding, announcement banner, and incident timeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sentinel.config import StatusPageConfig
from sentinel.state import TargetState, TargetStatus
from sentinel.status_page import StatusPageExporter
from sentinel.storage import IncidentRecord


def test_status_page_custom_branding() -> None:
    config = StatusPageConfig(
        title="Acme Global Infrastructure",
        company_name="Acme Corp",
        logo_url="https://acme.example.com/logo.svg",
    )
    exporter = StatusPageExporter(config=config)
    state = TargetState(name="api-gateway", url="https://api.acme.com", status=TargetStatus.UP)
    html = exporter.render_page([state])

    assert "<title>Acme Global Infrastructure</title>" in html
    assert "Acme Corp" in html
    assert '<img src="https://acme.example.com/logo.svg"' in html


def test_status_page_announcement_banner() -> None:
    config = StatusPageConfig(
        announcement_banner="Scheduled maintenance on cluster B tonight.",
        announcement_type="warning",
    )
    exporter = StatusPageExporter(config=config)
    state = TargetState(name="web", url="https://web.acme.com", status=TargetStatus.UP)
    html = exporter.render_page([state])

    assert "banner-warning" in html
    assert "Scheduled maintenance on cluster B tonight." in html


def test_status_page_incident_timeline() -> None:
    exporter = StatusPageExporter()
    state = TargetState(name="checkout", url="https://pay.acme.com", status=TargetStatus.UP)

    start_time = datetime(2026, 9, 16, 14, 0, 0, tzinfo=UTC)
    resolved_time = start_time + timedelta(minutes=24, seconds=10)
    incidents = [
        IncidentRecord(
            id=1,
            target_name="checkout",
            started_at=start_time,
            resolved_at=resolved_time,
            duration_seconds=1450.0,
            error_reason="PostgreSQL connection pool exhausted",
        )
    ]

    html = exporter.render_page([state], recent_incidents=incidents)
    assert "Past Incidents (Last 7 Days)" in html
    assert "checkout" in html
    assert "24 minutes, 10 seconds" in html
    assert "PostgreSQL connection pool exhausted" in html
    assert "Resolved" in html


def test_status_page_maintenance_badge() -> None:
    exporter = StatusPageExporter()
    state = TargetState(name="worker-cluster", url="https://worker.acme.com", status=TargetStatus.DOWN)

    # With muted targets set
    html = exporter.render_page([state], muted_targets={"worker-cluster"})
    assert "MAINTENANCE" in html
    assert "Under scheduled maintenance" in html
