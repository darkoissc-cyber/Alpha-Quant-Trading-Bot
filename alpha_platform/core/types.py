from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    FLAT = "FLAT"

class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"

class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

class StrategyStage(str, Enum):
    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    VALIDATION = "VALIDATION"
    SHADOW = "SHADOW"
    PAPER = "PAPER"
    SMALL_LIVE = "SMALL_LIVE"
    PRODUCTION = "PRODUCTION"
    RETIRED = "RETIRED"

class MarketSession(str, Enum):
    ASIAN = "ASIAN"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"
    OVERLAP = "OVERLAP"

@dataclass
class Tick:
    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    volume: float
    flags: int = 0
    
    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0
    
    @property
    def spread(self) -> float:
        return self.ask - self.bid

@dataclass
class Bar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    tick_count: int = 0

@dataclass
class TradeCandidate:
    candidate_id: str
    strategy_id: str
    symbol: str
    timestamp: datetime
    signal_type: SignalType
    entry_price: float
    stop_loss: float
    take_profit: float
    holding_period_bars: int
    confidence_score: float
    features_snapshot: Dict[str, float] = field(default_factory=dict)
    composite_score: float = 0.0
    quality_grade: str = "C"
    self_critic_justification: str = ""

@dataclass
class MetaLabelResult:
    candidate_id: str
    probability_success: float
    is_approved: bool
    calibrated_prob: float
    model_version: str

@dataclass
class RiskCheckResult:
    passed: bool
    veto_reason: Optional[str] = None
    scaled_position_size: float = 0.0
    soft_limit_exceeded: bool = False
    hard_limit_exceeded: bool = False

@dataclass
class Position:
    position_id: str
    strategy_id: str
    symbol: str
    signal_type: SignalType
    volume: float
    entry_price: float
    current_price: float
    stop_loss: float
    take_profit: float
    unrealized_pnl: float
    open_time: datetime

class ModelGovernanceRecord(BaseModel):
    model_id: str
    version: str
    training_date: str
    dataset_hash: str
    features: List[str]
    parameters: Dict[str, Any]
    brier_score: float
    pbo_score: float
    dsr_score: float
    stage: StrategyStage
