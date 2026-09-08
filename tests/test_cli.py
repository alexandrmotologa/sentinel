"""Unit tests for Sentinel Typer CLI commands."""

import time
from typer.testing import CliRunner
from sentinel.cli import app
from sentinel.engine import get_heartbeat_path


runner = CliRunner()


def test_cli_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "Sentinel v0.1.0" in result.output


def test_cli_check_config_valid():
    result = runner.invoke(app, ["check-config", "sites.example.yaml"])
    assert result.exit_code == 0
    assert "Configuration valid" in result.output
    assert "Configured Targets" in result.output


def test_cli_check_config_missing():
    result = runner.invoke(app, ["check-config", "nonexistent.yaml"])
    assert result.exit_code == 1
    assert "File not found" in result.output


def test_cli_healthcheck(monkeypatch, tmp_path):
    test_heartbeat = tmp_path / "sentinel.heartbeat"
    monkeypatch.setenv("SENTINEL_HEARTBEAT_PATH", str(test_heartbeat))

    # Stale/missing file
    result = runner.invoke(app, ["healthcheck"])
    assert result.exit_code == 1
    assert "ERROR: Daemon heartbeat is stale or missing." in result.output

    # Fresh heartbeat
    test_heartbeat.write_text(str(time.time()), encoding="utf-8")
    result = runner.invoke(app, ["healthcheck"])
    assert result.exit_code == 0
    assert "OK: Daemon heartbeat is fresh." in result.output


def test_cli_probe_success(monkeypatch, tmp_path):
    import httpx
    from sentinel import evaluator

    yaml_content = """
targets:
  - name: "API Test"
    url: "https://mock.api/health"
    expect:
      status_code: 200
"""
    cfg_file = tmp_path / "sites.yaml"
    cfg_file.write_text(yaml_content, encoding="utf-8")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, text="OK")

    transport = httpx.MockTransport(mock_handler)
    orig_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: orig_client(transport=transport, **kwargs),
    )

    # Standard table output
    result = runner.invoke(app, ["probe", str(cfg_file)])
    assert result.exit_code == 0
    assert "Target Probe Results" in result.output
    assert "PASS" in result.output

    # JSON output
    result_json = runner.invoke(app, ["probe", str(cfg_file), "--json"])
    assert result_json.exit_code == 0
    assert '"all_passed": true' in result_json.output
    assert '"API Test"' in result_json.output
