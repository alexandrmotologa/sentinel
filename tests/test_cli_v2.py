"""Tests for Sentinel CLI commands: mute, unmute, mutes, and incidents."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from sentinel.cli import app
from sentinel.storage import IncidentStore

runner = CliRunner()


def test_cli_mute_and_unmute_commands(tmp_path: Path) -> None:
    mutes_file = tmp_path / "sentinel_mutes.json"

    # 1. Mute target
    res = runner.invoke(
        app,
        [
            "mute",
            "api-service",
            "--duration",
            "45",
            "--reason",
            "Kernel upgrade",
            "--mutes-file",
            str(mutes_file),
        ],
    )
    assert res.exit_code == 0
    assert "Target 'api-service' muted for 45m" in res.stdout

    # 2. List mutes
    res_list = runner.invoke(app, ["mutes", "--mutes-file", str(mutes_file)])
    assert res_list.exit_code == 0
    assert "api-service" in res_list.stdout
    assert "Kernel upgrade" in res_list.stdout

    # 3. Unmute target
    res_unmute = runner.invoke(app, ["unmute", "api-service", "--mutes-file", str(mutes_file)])
    assert res_unmute.exit_code == 0
    assert "Target 'api-service' unmuted" in res_unmute.stdout

    # 4. List mutes after unmute
    res_list_empty = runner.invoke(app, ["mutes", "--mutes-file", str(mutes_file)])
    assert res_list_empty.exit_code == 0
    assert "No active maintenance mutes" in res_list_empty.stdout


def test_cli_incidents_command(tmp_path: Path) -> None:
    db_file = tmp_path / "sentinel.db"
    store = IncidentStore(db_file)
    store.record_outage_start("db-primary", error_reason="Disk full on /var/lib")
    store.record_recovery("db-primary")
    store.close()

    res = runner.invoke(app, ["incidents", "--db", str(db_file), "--days", "7"])
    assert res.exit_code == 0
    assert "db-primary" in res.stdout
    assert "Disk full" in res.stdout


def test_cli_check_config_with_ping_and_maintenance(tmp_path: Path) -> None:
    cfg_file = tmp_path / "sites_v2.yaml"
    cfg_file.write_text("""
global:
  default_interval: 30s
  db_path: "data/sentinel.db"

ping_targets:
  - name: "gateway-router"
    host: "192.168.1.1"
    count: 3
    expect:
      max_latency_ms: 10
      max_packet_loss_percent: 0

maintenance:
  - name: "weekend-reboot"
    targets: ["gateway-router"]
    schedule: "weekly sun 02:00-03:00"
    reason: "Scheduled reboot"

status_page:
  title: "Network Status"
  company_name: "Internal Net"
  announcement_banner: "All systems nominal"
""", encoding="utf-8")

    res = runner.invoke(app, ["check-config", str(cfg_file)])
    assert res.exit_code == 0
    assert "gateway-router" in res.stdout
    assert "PING" in res.stdout
