from abc import ABC, abstractmethod
from typing import List, Optional
from alpha_platform.core.types import Bar, Tick, TradeCandidate
from alpha_platform.alpha_research.hypothesis import AlphaHypothesis

class BaseStrategy(ABC):
    def __init__(self, strategy_id: str, hypothesis: AlphaHypothesis):
        self.strategy_id = strategy_id
        self.hypothesis = hypothesis
        self.hypothesis.validate()

    @abstractmethod
    def generate_candidates(self, symbol: str, bars: List[Bar], current_tick: Optional[Tick] = None) -> List[TradeCandidate]:
        """
        Strategies ONLY generate trade candidates.
        They CANNOT execute orders directly.
        """
        pass
