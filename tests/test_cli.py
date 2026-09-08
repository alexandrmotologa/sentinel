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
