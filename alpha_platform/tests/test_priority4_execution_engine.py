import unittest
from alpha_platform.execution_engine.advanced_execution import (
    DuplicateOrderGuard,
    ExecutionRetryQueue,
    ExecutionAuditLogger,
    BrokerReconnectManager
)
from alpha_platform.execution_engine.order_reconciler import OrderReconciler

class TestPriority4ExecutionEngineUpgrade(unittest.TestCase):
    def setUp(self):
        self.duplicate_guard = DuplicateOrderGuard(ttl_seconds=2.0)
        self.retry_queue = ExecutionRetryQueue(max_retries=2)
        self.audit_logger = ExecutionAuditLogger()
        self.reconnect_mgr = BrokerReconnectManager()
        self.reconciler = OrderReconciler()

    def test_duplicate_order_prevention(self):
        # First check -> Not duplicate
        is_dup1 = self.duplicate_guard.is_duplicate("XAUUSD", "BUY", 0.10)
        self.assertFalse(is_dup1)
        
        # Second check within TTL window -> Duplicate!
        is_dup2 = self.duplicate_guard.is_duplicate("XAUUSD", "BUY", 0.10)
        self.assertTrue(is_dup2)

    def test_retry_queue_flow(self):
        order_payload = {"symbol": "EURUSD", "signal": "BUY", "volume": 0.05}
        self.retry_queue.add_failed_order(order_payload, attempt=1)
        self.assertEqual(len(self.retry_queue.pending_retries), 1)

    def test_execution_audit_logging(self):
        self.audit_logger.log_execution(
            symbol="XAUUSD",
            action="SEND_ORDER",
            status="FILLED",
            latency_ms=125.4,
            expected_price=2000.0,
            fill_price=2000.05
        )
        summary = self.audit_logger.get_audit_summary()
        self.assertEqual(summary["total_executions"], 1)
        self.assertGreater(summary["avg_latency_ms"], 0.0)

    def test_order_reconciler(self):
        target_positions = [{"position_id": "pos_1", "symbol": "XAUUSD"}]
        live_positions = [{"ticket": "pos_1", "symbol": "XAUUSD"}, {"ticket": "pos_2_orphan", "symbol": "EURUSD"}]
        actions = self.reconciler.reconcile(target_positions, live_positions)
        self.assertTrue(any(a["action"] == "IMPORT_ORPHAN" for a in actions))

if __name__ == "__main__":
    unittest.main()
