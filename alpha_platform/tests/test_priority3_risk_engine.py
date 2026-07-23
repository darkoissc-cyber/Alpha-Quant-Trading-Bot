import unittest
import pandas as pd
from datetime import datetime
from alpha_platform.core.types import Position, SignalType
from alpha_platform.risk_engine.python_binding import RiskEngine
from alpha_platform.risk_engine.advanced_risk import (
    CorrelationMatrixEngine,
    RiskBudgetManager,
    DynamicPositionRiskManager
)

class TestPriority3RiskEngineUpgrade(unittest.TestCase):
    def setUp(self):
        self.risk_engine = RiskEngine(initial_equity=10000.0)
        self.corr_engine = CorrelationMatrixEngine()
        self.budget_manager = RiskBudgetManager()
        self.pos_manager = DynamicPositionRiskManager()

    def test_correlation_matrix_veto(self):
        df_returns = pd.DataFrame({
            "XAUUSD": [0.01, 0.02, -0.01, 0.03],
            "EURUSD": [0.009, 0.019, -0.011, 0.029]  # Highly correlated
        })
        corr_matrix = self.corr_engine.compute_correlation_matrix(df_returns)
        allowed, reason = self.corr_engine.is_exposure_allowed(
            proposed_symbol="EURUSD",
            active_positions=[{"symbol": "XAUUSD"}],
            correlation_matrix=corr_matrix
        )
        self.assertFalse(allowed)
        self.assertIn("High correlation", reason)

    def test_circuit_breaker_consecutive_losses(self):
        self.budget_manager.record_trade_result(-100.0)
        self.budget_manager.record_trade_result(-100.0)
        self.budget_manager.record_trade_result(-100.0)
        ok, reason = self.budget_manager.check_risk_budget(9700.0, 10000.0, 10000.0, 10000.0)
        self.assertFalse(ok)
        self.assertIn("Risk Cooldown Active", reason)

    def test_auto_break_even_and_trailing_stop(self):
        pos = Position(
            position_id="pos_123",
            strategy_id="STRAT_1",
            symbol="XAUUSD",
            signal_type=SignalType.BUY,
            volume=0.04,
            entry_price=2000.0,
            current_price=2000.0,
            stop_loss=1990.0,
            take_profit=2030.0,
            unrealized_pnl=0.0,
            open_time=datetime.utcnow()
        )
        # Entry=2000, SL=1990 -> Risk dist=10. Price reaches 2012 (1.2 R)
        modify_sl, partial_close = self.pos_manager.evaluate_active_position_modifications(
            position=pos,
            current_price=2012.0,
            current_atr=2.0
        )
        self.assertIsNotNone(modify_sl)
        self.assertGreaterEqual(modify_sl.new_stop_loss, 2000.0)  # Locked in Break-Even or higher Trailing profit!

if __name__ == "__main__":
    unittest.main()
