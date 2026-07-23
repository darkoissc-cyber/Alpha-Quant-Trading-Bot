from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, List

from alpha_platform.config.settings import settings
from alpha_platform.api.websocket_manager import ws_manager
from alpha_platform.risk_engine.python_binding import RiskEngine
from alpha_platform.model_governance.registry import ModelRegistry
from alpha_platform.statistical_validation.walk_forward import StatisticalValidationGate
from alpha_platform.stress_testing.stress_engine import StressTestingEngine
from alpha_platform.execution_analytics.execution_tracker import ExecutionQualityTracker

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Institutional Quantitative Trading, AI Meta-Labeling & Risk Engine Gateway API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Instance State
risk_engine = RiskEngine(initial_equity=10000.0)
model_registry = ModelRegistry()
validation_gate = StatisticalValidationGate()
stress_engine = StressTestingEngine()
execution_tracker = ExecutionQualityTracker()

@app.get("/")
def read_root():
    return {
        "status": "ONLINE",
        "system": settings.PROJECT_NAME,
        "broker": settings.BROKER_NAME,
        "instruments": settings.SUPPORTED_INSTRUMENTS
    }

@app.get("/api/portfolio")
def get_portfolio_overview() -> Dict[str, Any]:
    return {
        "equity": 10450.25,
        "balance": 10000.00,
        "peak_equity": 10500.00,
        "daily_pnl": 450.25,
        "daily_pnl_pct": 4.50,
        "current_drawdown_pct": 0.47,
        "soft_limit_pct": settings.SOFT_DAILY_DRAWDOWN_LIMIT_PCT,
        "hard_limit_pct": settings.HARD_TOTAL_DRAWDOWN_LIMIT_PCT,
        "active_positions_count": 2,
        "exposure": {
            "XAUUSD": 0.25,
            "EURUSD": 0.15,
            "GBPUSD": 0.10,
            "BTCUSD": 0.05
        }
    }

@app.get("/api/risk/status")
def get_risk_status() -> Dict[str, Any]:
    return {
        "emergency_kill_active": risk_engine.emergency_kill_active,
        "peak_equity": risk_engine.peak_equity,
        "soft_limit_hit": False,
        "hard_limit_hit": False,
        "max_leverage": settings.MAX_POSITION_LEVERAGE,
        "spread_limits": settings.MAX_SPREAD_PIPS_LIMIT
    }

@app.post("/api/risk/trigger-kill-switch")
def trigger_kill_switch():
    risk_engine.trigger_emergency_kill_switch("Triggered manually via Dashboard")
    return {"status": "EMERGENCY_KILL_ACTIVATED", "active": risk_engine.emergency_kill_active}

@app.get("/api/models")
def get_models() -> List[Dict[str, Any]]:
    models = model_registry.list_models()
    if not models:
        # Pre-populate demonstration record
        return [
            {
                "model_id": "META_LGBM_XAU_v1.2",
                "version": "1.2.0",
                "training_date": "2026-07-20T10:00:00",
                "dataset_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "features": ["momentum_rsi", "volatility_gk", "tick_imbalance", "gold_dxy_beta"],
                "brier_score": 0.142,
                "pbo_score": 0.04,
                "dsr_score": 2.15,
                "stage": "PRODUCTION"
            }
        ]
    return [m.dict() for m in models]

@app.get("/api/strategies")
def get_strategies() -> List[Dict[str, Any]]:
    return [
        {
            "id": "STRAT_TREND_01",
            "name": "Multi-Timeframe Trend Following",
            "symbol": "XAUUSD",
            "type": "Trend Following",
            "stage": "PRODUCTION",
            "win_rate": 0.62,
            "sharpe_ratio": 2.10,
            "trades": 142,
            "pbo": 0.04,
            "dsr": 2.15,
            "status": "ACTIVE"
        },
        {
            "id": "STRAT_BREAKOUT_01",
            "name": "Volatility Compression Breakout",
            "symbol": "BTCUSD",
            "type": "Breakout",
            "stage": "PAPER",
            "win_rate": 0.58,
            "sharpe_ratio": 1.85,
            "trades": 88,
            "pbo": 0.07,
            "dsr": 1.72,
            "status": "PAPER_TRADING"
        },
        {
            "id": "STRAT_MEAN_REV_01",
            "name": "Bollinger Deviation Reversion",
            "symbol": "EURUSD",
            "type": "Mean Reversion",
            "stage": "VALIDATION",
            "win_rate": 0.54,
            "sharpe_ratio": 1.40,
            "trades": 64,
            "pbo": 0.12,
            "dsr": 1.25,
            "status": "UNDER_REVIEW"
        }
    ]

@app.post("/api/stress-test/run")
def run_stress_test():
    res = stress_engine.run_stress_test_suite()
    return res

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Echo heartbeat or state stream
            await websocket.send_text(data)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
