from typing import Optional, List, Dict, Any
import pandas as pd
from alpha_platform.core.types import RiskCheckResult
from alpha_platform.config.settings import settings
from alpha_platform.config.logging_config import logger
from alpha_platform.risk_engine.advanced_risk import (
    CorrelationMatrixEngine,
    RiskBudgetManager,
    DynamicPositionRiskManager
)

class RiskEngine:
    """
    Python wrapper enforcing Risk Engine authority.
    Evaluates Soft limits (1.5% daily drawdown), Hard limits (3.5% total drawdown kill switch),
    Correlation Matrix vetoes, Periodic Risk Budgets, and Dynamic Position Scaling.
    """

    def __init__(self, initial_equity: float = 10000.0):
        self.peak_equity = initial_equity
        self.day_start_equity = initial_equity
        self.week_start_equity = initial_equity
        self.month_start_equity = initial_equity
        self.emergency_kill_active = False

        # Advanced Risk Subsystems
        self.correlation_engine = CorrelationMatrixEngine(max_allowed_correlation=0.75)
        self.budget_manager = RiskBudgetManager(
            daily_budget_pct=settings.SOFT_DAILY_DRAWDOWN_LIMIT_PCT,
            weekly_budget_pct=5.0,
            monthly_budget_pct=10.0,
            max_consecutive_losses=3
        )
        self.position_risk_manager = DynamicPositionRiskManager()

    def reset_daily_equity(self, current_equity: float):
        self.day_start_equity = current_equity

    def trigger_emergency_kill_switch(self, reason: str = "User initiated emergency stop"):
        self.emergency_kill_active = True
        logger.critical(f"EMERGENCY KILL SWITCH ACTIVATED: {reason}")

    def evaluate_candidate(
        self,
        symbol: str,
        current_equity: float,
        proposed_volume: float,
        entry_price: float,
        stop_loss: float,
        current_spread_pips: float,
        active_positions: Optional[List[Dict[str, Any]]] = None,
        correlation_matrix: Optional[pd.DataFrame] = None
    ) -> RiskCheckResult:
        # Update Peak Equity
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity

        # 1. Emergency Kill Switch Check
        if self.emergency_kill_active:
            return RiskCheckResult(
                passed=False,
                veto_reason="Emergency Kill Switch is ACTIVE. Order Vetoed.",
                scaled_position_size=0.0,
                soft_limit_exceeded=True,
                hard_limit_exceeded=True
            )

        # 2. Hard Drawdown Check (3.5% Limit -> Immediate Emergency Stop)
        total_dd_pct = (self.peak_equity - current_equity) / self.peak_equity * 100.0 if self.peak_equity > 0 else 0.0
        if total_dd_pct >= settings.HARD_TOTAL_DRAWDOWN_LIMIT_PCT:
            self.trigger_emergency_kill_switch(f"Hard total drawdown limit hit: {total_dd_pct:.2f}%")
            return RiskCheckResult(
                passed=False,
                veto_reason=f"Hard total drawdown limit hit: {total_dd_pct:.2f}% >= {settings.HARD_TOTAL_DRAWDOWN_LIMIT_PCT}%. VETO.",
                scaled_position_size=0.0,
                soft_limit_exceeded=True,
                hard_limit_exceeded=True
            )

        # 3. Periodic Risk Budget & Circuit Breaker Check
        budget_ok, budget_reason = self.budget_manager.check_risk_budget(
            current_equity=current_equity,
            day_start_equity=self.day_start_equity,
            week_start_equity=self.week_start_equity,
            month_start_equity=self.month_start_equity
        )
        if not budget_ok:
            return RiskCheckResult(
                passed=False,
                veto_reason=f"Risk Budget Veto: {budget_reason}",
                scaled_position_size=0.0,
                soft_limit_exceeded=True,
                hard_limit_exceeded=False
            )

        # 4. Correlation Matrix Veto Check
        if active_positions and correlation_matrix is not None and not correlation_matrix.empty:
            corr_ok, corr_reason = self.correlation_engine.is_exposure_allowed(
                proposed_symbol=symbol,
                active_positions=active_positions,
                correlation_matrix=correlation_matrix
            )
            if not corr_ok:
                return RiskCheckResult(
                    passed=False,
                    veto_reason=f"Correlation Veto: {corr_reason}",
                    scaled_position_size=0.0,
                    soft_limit_exceeded=False,
                    hard_limit_exceeded=False
                )

        # 5. Soft Daily Loss Check (1.5% Limit -> De-risk position size by 50%)
        daily_dd_pct = (self.day_start_equity - current_equity) / self.day_start_equity * 100.0 if self.day_start_equity > 0 else 0.0
        soft_limit_hit = daily_dd_pct >= settings.SOFT_DAILY_DRAWDOWN_LIMIT_PCT
        risk_scale = 0.5 if soft_limit_hit else 1.0

        # 6. Spread Protection
        max_spread = settings.MAX_SPREAD_PIPS_LIMIT.get(symbol, 50.0)
        if current_spread_pips > max_spread:
            return RiskCheckResult(
                passed=False,
                veto_reason=f"Spread anomaly on {symbol}: {current_spread_pips:.1f} pips > max {max_spread:.1f} pips",
                scaled_position_size=0.0,
                soft_limit_exceeded=soft_limit_hit,
                hard_limit_exceeded=False
            )

        # 7. Adaptive Position Sizing
        sl_distance = abs(entry_price - stop_loss)
        risk_amount = current_equity * 0.01 * risk_scale  # 1% risk per trade scaled
        
        calculated_vol = proposed_volume
        if sl_distance > 0:
            calculated_vol = risk_amount / sl_distance

        final_vol = min(proposed_volume, calculated_vol) * risk_scale

        return RiskCheckResult(
            passed=True,
            veto_reason=None,
            scaled_position_size=float(final_vol),
            soft_limit_exceeded=soft_limit_hit,
            hard_limit_exceeded=False
        )
