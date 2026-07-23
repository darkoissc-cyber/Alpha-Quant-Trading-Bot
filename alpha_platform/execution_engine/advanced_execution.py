import time
import asyncio
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from alpha_platform.config.logging_config import logger
from alpha_platform.system.metrics import metrics_collector

@dataclass
class AuditLogEntry:
    timestamp: str
    symbol: str
    action: str
    status: str
    latency_ms: float
    slippage_pips: float
    details: Dict[str, Any] = field(default_factory=dict)

class DuplicateOrderGuard:
    """
    Prevents duplicate order submissions within a configurable time window.
    """
    def __init__(self, ttl_seconds: float = 5.0):
        self.ttl_seconds = ttl_seconds
        self.recent_orders: Dict[str, float] = {}

    def _generate_order_key(self, symbol: str, signal_type: str, volume: float) -> str:
        return f"{symbol}_{signal_type.upper()}_{volume:.2f}"

    def is_duplicate(self, symbol: str, signal_type: str, volume: float) -> bool:
        now = time.time()
        key = self._generate_order_key(symbol, signal_type, volume)
        
        # Clean expired keys
        expired = [k for k, ts in self.recent_orders.items() if now - ts > self.ttl_seconds]
        for k in expired:
            del self.recent_orders[k]

        if key in self.recent_orders:
            logger.warning(f"DUPLICATE ORDER BLOCKED: {key} submitted within {self.ttl_seconds}s window.")
            return True

        self.recent_orders[key] = now
        return False

class ExecutionRetryQueue:
    """
    Order Retry Queue with exponential backoff for transient broker failures.
    """
    def __init__(self, max_retries: int = 3, base_delay_ms: float = 100.0):
        self.max_retries = max_retries
        self.base_delay_ms = base_delay_ms
        self.pending_retries: List[Dict[str, Any]] = []

    def add_failed_order(self, order_payload: Dict[str, Any], attempt: int = 1):
        if attempt <= self.max_retries:
            order_payload["attempt"] = attempt
            order_payload["next_retry_time"] = time.time() + ((self.base_delay_ms * (2 ** (attempt - 1))) / 1000.0)
            self.pending_retries.append(order_payload)
            logger.info(f"Order queued for retry attempt {attempt}/{self.max_retries}: {order_payload.get('symbol')}")

    def pop_ready_orders() -> List[Dict[str, Any]]:
        pass

    def get_ready_orders(self) -> List[Dict[str, Any]]:
        now = time.time()
        ready = [o for o in self.pending_retries if o["next_retry_time"] <= now]
        self.pending_retries = [o for o in self.pending_retries if o["next_retry_time"] > now]
        return ready

class ExecutionAuditLogger:
    """
    Audit Logger for tracking order roundtrip latency, slippage, and broker execution quality.
    """
    def __init__(self, max_logs: int = 1000):
        self.max_logs = max_logs
        self.audit_logs: List[AuditLogEntry] = []

    def log_execution(
        self,
        symbol: str,
        action: str,
        status: str,
        latency_ms: float,
        expected_price: float,
        fill_price: float,
        details: Optional[Dict[str, Any]] = None
    ):
        slippage_pips = abs(fill_price - expected_price) if fill_price > 0 and expected_price > 0 else 0.0
        
        entry = AuditLogEntry(
            timestamp=datetime.utcnow().isoformat() + "Z",
            symbol=symbol,
            action=action,
            status=status,
            latency_ms=round(latency_ms, 2),
            slippage_pips=round(slippage_pips, 4),
            details=details or {}
        )
        
        self.audit_logs.append(entry)
        if len(self.audit_logs) > self.max_logs:
            self.audit_logs.pop(0)

        # Record system metrics
        metrics_collector.record_histogram("execution_latency_ms", latency_ms)
        metrics_collector.record_histogram("execution_slippage_pips", slippage_pips)
        metrics_collector.increment_counter(f"execution_{status.lower()}")

    def get_audit_summary(self) -> Dict[str, Any]:
        if not self.audit_logs:
            return {"total_executions": 0, "avg_latency_ms": 0.0, "avg_slippage_pips": 0.0}

        avg_lat = sum(l.latency_ms for l in self.audit_logs) / len(self.audit_logs)
        avg_slip = sum(l.slippage_pips for l in self.audit_logs) / len(self.audit_logs)
        return {
            "total_executions": len(self.audit_logs),
            "avg_latency_ms": round(avg_lat, 2),
            "avg_slippage_pips": round(avg_slip, 4),
            "recent_logs": [l.__dict__ for l in self.audit_logs[-10:]]
        }

class BrokerReconnectManager:
    """
    Automatic broker reconnect and session keep-alive manager.
    """
    def __init__(self):
        self.is_connected = False
        self.last_heartbeat = time.time()

    def record_heartbeat(self):
        self.last_heartbeat = time.time()
        self.is_connected = True

    def check_connection(self, max_stale_seconds: float = 15.0) -> bool:
        if time.time() - self.last_heartbeat > max_stale_seconds:
            self.is_connected = False
            logger.warning("Broker connection stale or disconnected. Triggering reconnect sequence.")
            return False
        return True
