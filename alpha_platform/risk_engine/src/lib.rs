pub mod limits;
pub mod drawdown;
pub mod leverage;

use limits::{RiskLimits, RiskVerdict};
use drawdown::calculate_drawdown_pct;

pub struct RustRiskEngine {
    limits: RiskLimits,
    peak_equity: f64,
    day_start_equity: f64,
}

impl RustRiskEngine {
    pub fn new(initial_equity: f64, limits: RiskLimits) -> Self {
        Self {
            limits,
            peak_equity: initial_equity,
            day_start_equity: initial_equity,
        }
    }

    pub fn update_equity(&mut self, current_equity: f64) {
        if current_equity > self.peak_equity {
            self.peak_equity = current_equity;
        }
    }

    pub fn reset_daily_equity(&mut self, current_equity: f64) {
        self.day_start_equity = current_equity;
    }

    pub fn set_emergency_kill_switch(&mut self, active: bool) {
        self.limits.emergency_kill_active = active;
    }

    pub fn evaluate_order(
        &mut self,
        current_equity: f64,
        proposed_volume: f64,
        entry_price: f64,
        stop_loss_distance: f64,
        current_spread_pips: f64,
    ) -> RiskVerdict {
        self.update_equity(current_equity);

        // 1. Emergency Kill Switch Check
        if self.limits.emergency_kill_active {
            return RiskVerdict {
                passed: false,
                veto_reason: Some("Emergency Kill Switch is ACTIVE. Trade rejected.".into()),
                scaled_position_size: 0.0,
                soft_limit_exceeded: true,
                hard_limit_exceeded: true,
            };
        }

        // 2. Hard Total Drawdown Check (3.5% Drawdown -> Hard Stop)
        let total_dd = calculate_drawdown_pct(self.peak_equity, current_equity);
        if total_dd >= self.limits.hard_total_drawdown_pct {
            self.limits.emergency_kill_active = true;
            return RiskVerdict {
                passed: false,
                veto_reason: Some(format!("Hard Drawdown limit exceeded: {:.2}% >= {:.2}%. EMERGENCY KILL ACTIVATED.", total_dd, self.limits.hard_total_drawdown_pct)),
                scaled_position_size: 0.0,
                soft_limit_exceeded: true,
                hard_limit_exceeded: true,
            };
        }

        // 3. Soft Daily Loss Check (1.5% Loss -> Auto-reduce position size by 50%)
        let daily_dd = calculate_drawdown_pct(self.day_start_equity, current_equity);
        let mut soft_limit_exceeded = false;
        let mut risk_scale_factor = 1.0;

        if daily_dd >= self.limits.soft_daily_drawdown_pct {
            soft_limit_exceeded = true;
            risk_scale_factor = 0.5; // Automatic 50% risk scaling
        }

        // 4. Spread Protection Check
        if current_spread_pips > self.limits.max_spread_pips {
            return RiskVerdict {
                passed: false,
                veto_reason: Some(format!("Spread anomaly: {:.1} pips > max {:.1} pips", current_spread_pips, self.limits.max_spread_pips)),
                scaled_position_size: 0.0,
                soft_limit_exceeded,
                hard_limit_exceeded: false,
            };
        }

        // 5. Volatility & Equity-Based Position Sizing
        let max_risk_amount = current_equity * 0.01 * risk_scale_factor; // Default 1% equity risk
        let calculated_size = if stop_loss_distance > 0.0 {
            max_risk_amount / stop_loss_distance
        } else {
            proposed_volume
        };

        let final_volume = calculated_size.min(proposed_volume) * risk_scale_factor;

        RiskVerdict {
            passed: true,
            veto_reason: None,
            scaled_position_size: final_volume,
            soft_limit_exceeded,
            hard_limit_exceeded: false,
        }
    }
}
