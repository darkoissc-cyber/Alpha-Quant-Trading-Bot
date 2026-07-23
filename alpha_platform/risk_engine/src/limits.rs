use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskLimits {
    pub soft_daily_drawdown_pct: f64,
    pub hard_total_drawdown_pct: f64,
    pub max_leverage: f64,
    pub max_spread_pips: f64,
    pub emergency_kill_active: bool,
}

impl Default for RiskLimits {
    fn default() -> Self {
        Self {
            soft_daily_drawdown_pct: 1.5,
            hard_total_drawdown_pct: 3.5,
            max_leverage: 30.0,
            max_spread_pips: 50.0,
            emergency_kill_active: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskVerdict {
    pub passed: bool,
    pub veto_reason: Option<String>,
    pub scaled_position_size: f64,
    pub soft_limit_exceeded: bool,
    pub hard_limit_exceeded: bool,
}
