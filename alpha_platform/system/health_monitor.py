import os
import sys
import time
import signal
import threading
from typing import Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime

from alpha_platform.config.logging_config import logger

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False

@dataclass
class SystemHealthMetrics:
    status: str  # HEALTHY, DEGRADED, CRITICAL
    uptime_seconds: float
    cpu_percent: float
    memory_used_mb: float
    memory_percent: float
    thread_count: int
    open_files_count: int
    warnings: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

class SystemHealthMonitor:
    """
    Production-grade System Health & Diagnostics Monitor.
    Tracks CPU, Memory, Threads, Latency, and OS process metrics.
    """
    def __init__(self):
        self.start_time = time.time()
        self.process = psutil.Process(os.getpid()) if HAS_PSUTIL else None
        # Prime psutil.cpu_percent() with a blocking call so subsequent
        # non-blocking calls return a real value (psutil returns 0.0 for the
        # first call when interval=None on Windows / Linux).
        if HAS_PSUTIL and self.process is not None:
            try:
                self.process.cpu_percent(interval=0.05)
            except Exception:
                pass

    def get_uptime_seconds(self) -> float:
        return time.time() - self.start_time

    def check_health(self) -> SystemHealthMetrics:
        metrics_dict = self.inspect_diagnostics()
        return SystemHealthMetrics(**metrics_dict)

    def inspect_diagnostics(self) -> Dict[str, Any]:
        uptime = self.get_uptime_seconds()
        cpu_pct = 0.0
        mem_mb = 0.0
        mem_pct = 0.0
        threads = threading.active_count()
        open_files = 0
        warnings = []

        if HAS_PSUTIL and self.process:
            try:
                # Non-blocking read (uses last primed sample)
                cpu_pct = self.process.cpu_percent(interval=None)
                mem_info = self.process.memory_info()
                mem_mb = mem_info.rss / (1024 * 1024)
                mem_pct = self.process.memory_percent()
                open_files = len(self.process.open_files())
            except Exception as e:
                logger.warning(f"Error reading psutil metrics: {e}")

        status = "HEALTHY"
        if cpu_pct > 85.0:
            status = "DEGRADED"
            warnings.append(f"High CPU utilization: {cpu_pct:.1f}%")
        if mem_pct > 85.0:
            status = "CRITICAL"
            warnings.append(f"High Memory utilization: {mem_pct:.1f}% ({mem_mb:.1f} MB)")

        metrics = SystemHealthMetrics(
            status=status,
            uptime_seconds=round(uptime, 2),
            cpu_percent=round(cpu_pct, 2),
            memory_used_mb=round(mem_mb, 2),
            memory_percent=round(mem_pct, 2),
            thread_count=threads,
            open_files_count=open_files,
            warnings=warnings
        )
        return metrics.__dict__

class GracefulShutdownHandler:
    """
    Handles OS termination signals (SIGINT, SIGTERM) to ensure clean state flush
    and graceful shutdown without order corruption.
    """
    def __init__(self):
        self.shutdown_requested = False
        self.cleanup_callbacks = []
        self._register_signals()

    def _register_signals(self):
        try:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        except (ValueError, AttributeError):
            # Signals might not bind on non-main threads
            pass

    def register_callback(self, callback_func):
        self.cleanup_callbacks.append(callback_func)

    def _signal_handler(self, sig, frame):
        if self.shutdown_requested:
            return
        self.shutdown_requested = True
        logger.warning(f"Received termination signal ({sig}). Initiating Graceful Shutdown...")
        for callback in self.cleanup_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error during shutdown callback: {e}")
        logger.info("Graceful Shutdown complete.")
        sys.exit(0)

health_monitor = SystemHealthMonitor()
shutdown_handler = GracefulShutdownHandler()
