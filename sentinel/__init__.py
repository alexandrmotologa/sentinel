"""Sentinel: Lightweight async uptime and API health monitoring daemon."""

from sentinel.config import SentinelConfig, TargetConfig, TCPTargetConfig
from sentinel.engine import HeartbeatService, SentinelEngine, TargetWorker
from sentinel.evaluator import BaseProbe, CheckResult, HttpProbe, TcpProbe
from sentinel.notifier import AlertDispatcher, BaseNotifier
from sentinel.server import MetricsServer
from sentinel.state import TargetState, TargetStatus

__version__ = "0.1.0"

__all__ = [
    "AlertDispatcher",
    "BaseNotifier",
    "BaseProbe",
    "CheckResult",
    "HeartbeatService",
    "HttpProbe",
    "MetricsServer",
    "SentinelConfig",
    "SentinelEngine",
    "TargetConfig",
    "TargetState",
    "TargetStatus",
    "TargetWorker",
    "TCPTargetConfig",
    "TcpProbe",
    "__version__",
]
