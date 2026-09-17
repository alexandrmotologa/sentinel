"""Sentinel: Lightweight async uptime and API health monitoring daemon."""

from sentinel.config import (
    DNSExpectConfig,
    DNSTargetConfig,
    MaintenanceWindowConfig,
    PingExpectConfig,
    PingTargetConfig,
    SentinelConfig,
    StatusPageConfig,
    TargetConfig,
    TCPTargetConfig,
)
from sentinel.engine import HeartbeatService, SentinelEngine, TargetWorker
from sentinel.evaluator import BaseProbe, CheckResult, DnsProbe, HttpProbe, PingProbe, TcpProbe, evaluate_ping_target
from sentinel.maintenance import MaintenanceManager
from sentinel.notifier import AlertDispatcher, BaseNotifier
from sentinel.server import MetricsServer
from sentinel.state import TargetState, TargetStatus
from sentinel.storage import IncidentRecord, IncidentStore

__version__ = "0.1.0"

__all__ = [
    "AlertDispatcher",
    "BaseNotifier",
    "BaseProbe",
    "CheckResult",
    "DNSExpectConfig",
    "DNSTargetConfig",
    "DnsProbe",
    "HeartbeatService",
    "HttpProbe",
    "IncidentRecord",
    "IncidentStore",
    "MaintenanceManager",
    "MaintenanceWindowConfig",
    "MetricsServer",
    "PingExpectConfig",
    "PingProbe",
    "PingTargetConfig",
    "SentinelConfig",
    "SentinelEngine",
    "StatusPageConfig",
    "TCPTargetConfig",
    "TargetConfig",
    "TargetState",
    "TargetStatus",
    "TargetWorker",
    "TcpProbe",
    "__version__",
    "evaluate_ping_target",
]

