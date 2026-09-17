"""Sentinel: Lightweight async uptime and API health monitoring daemon."""

from sentinel.config import DNSExpectConfig, DNSTargetConfig, SentinelConfig, TargetConfig, TCPTargetConfig
from sentinel.engine import HeartbeatService, SentinelEngine, TargetWorker
from sentinel.evaluator import BaseProbe, CheckResult, DnsProbe, HttpProbe, TcpProbe
from sentinel.notifier import AlertDispatcher, BaseNotifier
from sentinel.server import MetricsServer
from sentinel.state import TargetState, TargetStatus

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
    "MetricsServer",
    "SentinelConfig",
    "SentinelEngine",
    "TCPTargetConfig",
    "TargetConfig",
    "TargetState",
    "TargetStatus",
    "TargetWorker",
    "TcpProbe",
    "__version__",
]
