"""Unit tests for configuration dynamic reloading."""

from __future__ import annotations

import pytest

from sentinel.config import GlobalConfig, SentinelConfig, TargetConfig, TCPTargetConfig
from sentinel.engine import SentinelEngine
from sentinel.state import TargetStatus


def test_reload_config_add_remove_targets():
    initial_config = SentinelConfig(
        global_config=GlobalConfig(),
        targets=[
            TargetConfig(name="target-a", url="https://a.example.com"),
            TargetConfig(name="target-b", url="https://b.example.com"),
        ],
        tcp_targets=[
            TCPTargetConfig(name="tcp-a", host="127.0.0.1", port=5432),
        ],
    )
    engine = SentinelEngine(initial_config)

    assert "target-a" in engine.states
    assert "target-b" in engine.states
    assert "tcp-a" in engine.states

    # Reload with target-b removed, target-c added, tcp-a kept, tcp-b added
    new_config = SentinelConfig(
        global_config=GlobalConfig(),
        targets=[
            TargetConfig(name="target-a", url="https://a.example.com"),
            TargetConfig(name="target-c", url="https://c.example.com"),
        ],
        tcp_targets=[
            TCPTargetConfig(name="tcp-a", host="127.0.0.1", port=5432),
            TCPTargetConfig(name="tcp-b", host="127.0.0.1", port=6379),
        ],
    )

    engine.reload_config(new_config)

    assert "target-a" in engine.states
    assert "target-b" not in engine.states
    assert "target-c" in engine.states
    assert "tcp-a" in engine.states
    assert "tcp-b" in engine.states
