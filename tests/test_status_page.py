"""Unit tests for the embedded HTML/CSS web status page generator."""

from __future__ import annotations

from sentinel.evaluator import CheckResult
from sentinel.state import TargetState, TargetStatus
from sentinel.status_page import StatusPageExporter, generate_status_page


def test_status_page_rendering_empty():
    """Verify status page generates valid HTML structure with zero configured targets."""
    html_out = generate_status_page({})
    assert "<!DOCTYPE html>" in html_out
    assert "<title>Sentinel Status Page</title>" in html_out
    assert "ALL SYSTEMS OPERATIONAL" in html_out
    assert "0" in html_out
    assert "No endpoints configured for monitoring" in html_out


def test_status_page_all_up():
    """Verify status page reflects healthy state when all targets are UP."""
    state1 = TargetState(name="API Service", url="https://api.example.com/health")
    state1.update(
        CheckResult(passed=True, status_code=200, status_phrase="OK", latency_ms=45.0),
        debounce_threshold=2,
    )

    state2 = TargetState(name="Main DB", url="tcp://127.0.0.1:5432")
    state2.update(
        CheckResult(passed=True, status_code=None, status_phrase="Connected", latency_ms=12.0),
        debounce_threshold=2,
    )

    state3 = TargetState(name="DNS Gateway", url="dns://one.one.one.one (A)")
    state3.update(
        CheckResult(passed=True, status_code=None, status_phrase="Resolved", latency_ms=18.0),
        debounce_threshold=2,
    )

    states = {state1.name: state1, state2.name: state2, state3.name: state3}
    html_out = StatusPageExporter.render_page(states)

    assert "ALL SYSTEMS OPERATIONAL" in html_out
    assert "API Service" in html_out
    assert "Main DB" in html_out
    assert "DNS Gateway" in html_out
    assert 'class="type-pill http">HTTP<' in html_out
    assert 'class="type-pill tcp">TCP<' in html_out
    assert 'class="type-pill dns">DNS<' in html_out
    assert "3 UP &bull; 0 DOWN" in html_out
    assert "100.0%" in html_out
    assert "uptime-segment up" in html_out
    assert "SSL Active" in html_out


def test_status_page_partial_outage():
    """Verify status page reflects partial outage when one target is DOWN."""
    state_healthy = TargetState(name="Frontend", url="https://app.example.com")
    state_healthy.update(
        CheckResult(passed=True, status_code=200, status_phrase="OK", latency_ms=35.0),
        debounce_threshold=1,
    )

    state_failing = TargetState(name="Auth Service", url="https://auth.example.com")
    state_failing.update(
        CheckResult(
            passed=False,
            status_code=503,
            status_phrase="Service Unavailable",
            latency_ms=1200.0,
            error_reason="Connection refused on port 443",
        ),
        debounce_threshold=1,
    )

    states = {"Frontend": state_healthy, "Auth Service": state_failing}
    html_out = generate_status_page(states)

    assert "PARTIAL OUTAGE" in html_out
    assert "status-banner partial" in html_out
    assert "1 UP &bull; 1 DOWN" in html_out
    assert "Connection refused on port 443" in html_out
    assert 'class="status-pill down">DOWN<' in html_out


def test_status_page_major_outage():
    """Verify status page reflects major outage when all targets are DOWN."""
    state1 = TargetState(name="Cluster A", url="https://a.example.com")
    state1.update(
        CheckResult(passed=False, error_reason="Timeout", latency_ms=5000.0),
        debounce_threshold=1,
    )
    state2 = TargetState(name="Cluster B", url="https://b.example.com")
    state2.update(
        CheckResult(passed=False, error_reason="Host unreachable", latency_ms=5000.0),
        debounce_threshold=1,
    )

    states = {"Cluster A": state1, "Cluster B": state2}
    html_out = generate_status_page(states)

    assert "MAJOR OUTAGE" in html_out
    assert "status-banner major" in html_out
    assert "0 UP &bull; 2 DOWN" in html_out


def test_status_page_xss_escaping():
    """Verify that malicious script tags in target names or error strings are safely escaped."""
    malicious_name = '<script>alert("pwned")</script>'
    malicious_url = 'https://example.com/"><img src=x onerror=alert(1)>'
    malicious_error = '<b onmouseover=alert(1)>danger</b>'

    state = TargetState(name=malicious_name, url=malicious_url)
    state.status = TargetStatus.DOWN
    state.last_error_reason = malicious_error

    states = {malicious_name: state}
    html_out = generate_status_page(states)

    assert "<script>alert" not in html_out
    assert "&lt;script&gt;alert(&quot;pwned&quot;)&lt;/script&gt;" in html_out
    assert "<img src=x" not in html_out
    assert "<b onmouseover" not in html_out
    assert "&lt;b onmouseover=alert(1)&gt;danger&lt;/b&gt;" in html_out


def test_status_page_latency_coloring():
    """Verify latency color classes are assigned according to thresholds."""
    s_fast = TargetState(name="Fast", url="http://fast.com")
    s_fast.last_latency_ms = 40.0
    s_fast.status = TargetStatus.UP

    s_med = TargetState(name="Medium", url="http://med.com")
    s_med.last_latency_ms = 250.0
    s_med.status = TargetStatus.UP

    s_slow = TargetState(name="Slow", url="http://slow.com")
    s_slow.last_latency_ms = 650.0
    s_slow.status = TargetStatus.UP

    html_out = generate_status_page({"Fast": s_fast, "Med": s_med, "Slow": s_slow})
    assert "latency-fast" in html_out
    assert "latency-med" in html_out
    assert "latency-slow" in html_out
