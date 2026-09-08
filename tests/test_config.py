"""Unit tests for Sentinel configuration loading and validation."""

import os
import tempfile
from pathlib import Path
import pytest
from pydantic import ValidationError

from sentinel.config import (
    ExpectConfig,
    GlobalConfig,
    SentinelConfig,
    TargetConfig,
    parse_duration,
    resolve_env_strings,
)


def test_parse_duration():
    assert parse_duration(10) == 10.0
    assert parse_duration("10") == 10.0
    assert parse_duration("500ms") == 0.5
    assert parse_duration("30s") == 30.0
    assert parse_duration("2m") == 120.0
    assert parse_duration("1h") == 3600.0
    assert parse_duration("1d") == 86400.0


def test_parse_duration_invalid():
    with pytest.raises(ValueError):
        parse_duration("invalid")

    with pytest.raises(ValueError):
        parse_duration("10xyz")


def test_resolve_env_strings(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret_value")
    monkeypatch.setenv("TEST_HOST", "example.com")

    # Prefix resolution
    assert resolve_env_strings("env:TEST_KEY") == "secret_value"
    assert resolve_env_strings("env:NON_EXISTENT") == ""

    # Placeholder resolution
    assert resolve_env_strings("https://${TEST_HOST}/api") == "https://example.com/api"
    assert resolve_env_strings("${UNDEFINED:-fallback}") == "fallback"
    assert resolve_env_strings("${UNDEFINED}") == ""

    # Nested structures
    payload = {
        "token": "env:TEST_KEY",
        "url": "https://${TEST_HOST}/health",
        "list": ["env:TEST_KEY", "${TEST_HOST}"],
    }
    resolved = resolve_env_strings(payload)
    assert resolved["token"] == "secret_value"
    assert resolved["url"] == "https://example.com/health"
    assert resolved["list"] == ["secret_value", "example.com"]


def test_global_config_validation():
    cfg = GlobalConfig(
        default_interval="45s",
        default_timeout="5s",
        consecutive_failures_to_alert=3,
        daily_summary_time="14:30",
    )
    assert cfg.default_interval == 45.0
    assert cfg.default_timeout == 5.0
    assert cfg.consecutive_failures_to_alert == 3
    assert cfg.daily_summary_time == "14:30"


def test_global_config_invalid_time():
    with pytest.raises(ValidationError):
        GlobalConfig(daily_summary_time="25:00")

    with pytest.raises(ValidationError):
        GlobalConfig(daily_summary_time="invalid")


def test_target_defaults_inheritance():
    cfg = SentinelConfig(
        global_config=GlobalConfig(default_interval=40.0, default_timeout=8.0),
        targets=[
            TargetConfig(name="API", url="https://api.test.com"),
            TargetConfig(name="Web", url="https://web.test.com", interval=15.0),
        ],
    )
    assert cfg.targets[0].interval == 40.0
    assert cfg.targets[0].timeout == 8.0
    assert cfg.targets[1].interval == 15.0
    assert cfg.targets[1].timeout == 8.0


def test_load_yaml_file(tmp_path):
    yaml_content = """
global:
  default_interval: 30s
  default_timeout: 4s
  consecutive_failures_to_alert: 2
telegram:
  bot_token: "my_token"
  chat_id: "12345"
targets:
  - name: "Test Service"
    url: "https://test.local/health"
    expect:
      status_code: 200
      max_latency_ms: 500
      json:
        status: "ok"
"""
    file_path = tmp_path / "sites.yaml"
    file_path.write_text(yaml_content, encoding="utf-8")

    cfg = SentinelConfig.load_yaml(file_path)
    assert cfg.global_config.default_interval == 30.0
    assert cfg.telegram.bot_token == "my_token"
    assert len(cfg.targets) == 1
    assert cfg.targets[0].expect.json_match == {"status": "ok"}
