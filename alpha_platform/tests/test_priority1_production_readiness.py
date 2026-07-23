import unittest
from alpha_platform.config.settings import settings
from alpha_platform.config.logging_config import logger
from alpha_platform.system.health_monitor import health_monitor, SystemHealthMonitor
from alpha_platform.system.metrics import metrics_collector, measure_execution_time

class TestProductionReadinessPriority1(unittest.TestCase):
    def test_settings_load(self):
        self.assertIsNotNone(settings.PROJECT_NAME)
        self.assertIn("Exness", settings.BROKER_NAME)

    def test_logger_instance(self):
        self.assertIsNotNone(logger)

    def test_health_monitor_diagnostics(self):
        monitor = SystemHealthMonitor()
        metrics = monitor.inspect_diagnostics()
        self.assertIn("status", metrics)
        self.assertIn(metrics["status"], ["HEALTHY", "DEGRADED", "CRITICAL"])
        self.assertGreaterEqual(metrics["uptime_seconds"], 0.0)

    def test_metrics_collector(self):
        metrics_collector.increment_counter("test_counter", 1)
        metrics_collector.set_gauge("test_gauge", 99.5)
        with measure_execution_time("test_function_latency"):
            a = 1 + 1

        summary = metrics_collector.get_summary()
        self.assertIn("test_counter", summary["counters"])
        self.assertIn("test_gauge", summary["gauges"])
        self.assertIn("test_function_latency", summary["histograms"])

if __name__ == "__main__":
    unittest.main()
