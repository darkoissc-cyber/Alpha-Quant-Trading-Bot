pub fn calculate_drawdown_pct(peak_equity: f64, current_equity: f64) -> f64 {
    if peak_equity <= 0.0 {
        return 0.0;
    }
    let dd = (peak_equity - current_equity) / peak_equity * 100.0;
    if dd < 0.0 { 0.0 } else { dd }
}
