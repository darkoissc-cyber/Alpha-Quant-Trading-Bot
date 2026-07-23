import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from alpha_platform.core.types import Position, SignalType
from alpha_platform.config.logging_config import logger

@dataclass
class PartialCloseInstruction:
    position_id: str
    symbol: str
    volume_to_close: float
    reason: str

@dataclass
class ModifyStopLossInstruction:
    position_id: str
    symbol: str
    new_stop_loss: float
    reason: str

class CorrelationMatrixEngine:
    """
    Computes cross-asset price correlations and limits portfolio exposure to correlated assets.
    Prevents over-concentration in highly correlated assets (e.g. Gold & Euro buy trades).
    """
    def __init__(self, max_allowed_correlation: float = 0.75):
        self.max_allowed_correlation = max_allowed_correlation

    def compute_correlation_matrix(self, price_returns_df: pd.DataFrame) -> pd.DataFrame:
        if price_returns_df is None or price_returns_df.empty or len(price_returns_df.columns) < 2:
            return pd.DataFrame()
        return price_returns_df.corr()

    def is_exposure_allowed(
        self,
        proposed_symbol: str,
        active_positions: List[Dict[str, Any]],
        correlation_matrix: pd.DataFrame
    ) -> Tuple[bool, Optional[str]]:
        if correlation_matrix.empty or proposed_symbol not in correlation_matrix.columns:
            return True, None

        for pos in active_positions:
            active_sym = pos.get("symbol")
            if active_sym and active_sym in correlation_matrix.columns and active_sym != proposed_symbol:
                corr = abs(float(correlation_matrix.loc[proposed_symbol, active_sym]))
                if corr > self.max_allowed_correlation:
                    return False, f"High correlation ({corr:.2f} > {self.max_allowed_correlation}) between {proposed_symbol} and active position {active_sym}"

        return True, None

class RiskBudgetManager:
    """
    Institutional Periodic Risk Budget & Circuit Breaker Manager.
    Enforces Daily, Weekly, Monthly risk budgets and Consecutive Loss Control.
    """
    def __init__(
        self,
        daily_budget_pct: float = 2.0,
        weekly_budget_pct: float = 5.0,
        monthly_budget_pct: float = 10.0,
        max_consecutive_losses: int = 3
    ):
        self.daily_budget_pct = daily_budget_pct
        self.weekly_budget_pct = weekly_budget_pct
        self.monthly_budget_pct = monthly_budget_pct
        self.max_consecutive_losses = max_consecutive_losses

        self.consecutive_losses = 0
        self.cooldown_active = False

    def record_trade_result(self, profit: float):
        if profit < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.max_consecutive_losses:
                self.cooldown_active = True
                logger.warning(f"Circuit Breaker TRIGGERED: {self.consecutive_losses} consecutive losses. Cooldown activated.")
        else:
            self.consecutive_losses = 0
            self.cooldown_active = False

    def check_risk_budget(
        self,
        current_equity: float,
        day_start_equity: float,
        week_start_equity: float,
        month_start_equity: float
    ) -> Tuple[bool, Optional[str]]:
        if self.cooldown_active:
            return False, f"Risk Cooldown Active due to {self.consecutive_losses} consecutive losses."

        daily_loss_pct = (day_start_equity - current_equity) / day_start_equity * 100.0 if day_start_equity > 0 else 0.0
        if daily_loss_pct >= self.daily_budget_pct:
            return False, f"Daily Risk Budget Exceeded: {daily_loss_pct:.2f}% >= {self.daily_budget_pct}%"

        weekly_loss_pct = (week_start_equity - current_equity) / week_start_equity * 100.0 if week_start_equity > 0 else 0.0
        if weekly_loss_pct >= self.weekly_budget_pct:
            return False, f"Weekly Risk Budget Exceeded: {weekly_loss_pct:.2f}% >= {self.weekly_budget_pct}%"

        monthly_loss_pct = (month_start_equity - current_equity) / month_start_equity * 100.0 if month_start_equity > 0 else 0.0
        if monthly_loss_pct >= self.monthly_budget_pct:
            return False, f"Monthly Risk Budget Exceeded: {monthly_loss_pct:.2f}% >= {self.monthly_budget_pct}%"

        return True, None

class DynamicPositionRiskManager:
    """
    Manages active position protections: Auto Break-Even, Dynamic Trailing Stop,
    Partial Take Profits, and Equity Curve Scaling.
    """
    def __init__(self, break_even_rr: float = 1.0, trailing_stop_atr_mult: float = 2.0):
        self.break_even_rr = break_even_rr
        self.trailing_stop_atr_mult = trailing_stop_atr_mult

    def evaluate_active_position_modifications(
        self,
        position: Position,
        current_price: float,
        current_atr: float
    ) -> Tuple[Optional[ModifyStopLossInstruction], Optional[PartialCloseInstruction]]:
        modify_sl_instr = None
        partial_close_instr = None

        sl = position.stop_loss
        tp = position.take_profit
        entry = position.entry_price
        is_buy = position.signal_type == SignalType.BUY

        risk_dist = abs(entry - sl)
        if risk_dist <= 0:
            return None, None

        # 1. Automatic Break-Even Logic
        if is_buy and current_price >= entry + (self.break_even_rr * risk_dist):
            if sl < entry:
                modify_sl_instr = ModifyStopLossInstruction(
                    position_id=position.position_id,
                    symbol=position.symbol,
                    new_stop_loss=entry,
                    reason=f"Auto Break-Even triggered at {self.break_even_rr}R"
                )
        elif not is_buy and current_price <= entry - (self.break_even_rr * risk_dist):
            if sl > entry:
                modify_sl_instr = ModifyStopLossInstruction(
                    position_id=position.position_id,
                    symbol=position.symbol,
                    new_stop_loss=entry,
                    reason=f"Auto Break-Even triggered at {self.break_even_rr}R"
                )

        # 2. Dynamic Trailing Stop Logic based on ATR
        if current_atr > 0:
            if is_buy:
                proposed_trailing_sl = current_price - (self.trailing_stop_atr_mult * current_atr)
                current_sl_eval = modify_sl_instr.new_stop_loss if modify_sl_instr else sl
                if proposed_trailing_sl > current_sl_eval:
                    modify_sl_instr = ModifyStopLossInstruction(
                        position_id=position.position_id,
                        symbol=position.symbol,
                        new_stop_loss=float(proposed_trailing_sl),
                        reason=f"Dynamic ATR Trailing Stop updated"
                    )
            else:
                proposed_trailing_sl = current_price + (self.trailing_stop_atr_mult * current_atr)
                current_sl_eval = modify_sl_instr.new_stop_loss if modify_sl_instr else sl
                if proposed_trailing_sl < current_sl_eval:
                    modify_sl_instr = ModifyStopLossInstruction(
                        position_id=position.position_id,
                        symbol=position.symbol,
                        new_stop_loss=float(proposed_trailing_sl),
                        reason=f"Dynamic ATR Trailing Stop updated"
                    )

        # 3. Partial Take Profit Logic (50% partial close at 1.5 R)
        if is_buy and current_price >= entry + (1.5 * risk_dist):
            if position.volume >= 0.02:
                partial_close_instr = PartialCloseInstruction(
                    position_id=position.position_id,
                    symbol=position.symbol,
                    volume_to_close=round(position.volume * 0.5, 2),
                    reason="Partial Take Profit 50% executed at 1.5R"
                )
        elif not is_buy and current_price <= entry - (1.5 * risk_dist):
            if position.volume >= 0.02:
                partial_close_instr = PartialCloseInstruction(
                    position_id=position.position_id,
                    symbol=position.symbol,
                    volume_to_close=round(position.volume * 0.5, 2),
                    reason="Partial Take Profit 50% executed at 1.5R"
                )

        return modify_sl_instr, partial_close_instr
