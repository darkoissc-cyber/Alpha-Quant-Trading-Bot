import time
from typing import Dict, Any, List, Optional
from contextlib import contextmanager
from alpha_platform.config.logging_config import logger

class MetricsCollector:
    """
    In-memory metrics collector for system performance, execution latencies,
    and API transaction counts.
    """
    def __init__(self):
        self.counters: Dict[str, int] = {}
        self.gauges: Dict[str, float] = {}
        self.histograms: Dict[str, List[float]] = {}

    def increment_counter(self, name: str, value: int = 1):
        self.counters[name] = self.counters.get(name, 0) + value

    def set_gauge(self, name: str, value: float):
        self.gauges[name] = float(value)

    def record_histogram(self, name: str, value_ms: float):
        if name not in self.histograms:
            self.histograms[name] = []
        self.histograms[name].append(float(value_ms))
        # Keep window size capped at 1000 data points
        if len(self.histograms[name]) > 1000:
            self.histograms[name].pop(0)

    def get_summary(self) -> Dict[str, Any]:
        histogram_summary = {}
        for k, values in self.histograms.items():
            if values:
                histogram_summary[k] = {
                    "count": len(values),
                    "avg_ms": round(sum(values) / len(values), 2),
                    "min_ms": round(min(values), 2),
                    "max_ms": round(max(values), 2)
                }
        return {
            "counters": self.counters,
            "gauges": self.gauges,
            "histograms": histogram_summary
        }

metrics_collector = MetricsCollector()

@contextmanager
def measure_execution_time(metric_name: str):
    start_time = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        metrics_collector.record_histogram(metric_name, elapsed_ms)
