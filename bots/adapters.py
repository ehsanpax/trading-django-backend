import pandas as pd

from core.interfaces import StrategyInterface
from bots.base import BaseStrategy
from bots.engine import BacktestEngine

from typing import List, Dict

class LegacyStrategyAdapter(StrategyInterface):
    """
    Adapts a legacy BaseStrategy to the new StrategyInterface.
    It calls the legacy run_tick method and returns the actions for the engine to process.
    """
    def __init__(self, legacy_strategy: BaseStrategy, engine: BacktestEngine):
        self.legacy_strategy = legacy_strategy
        self.engine = engine

    def on_bar_close(self, ohlcv: pd.DataFrame) -> List[Dict]:
        """
        Calls the legacy strategy's run_tick() method and returns its actions.
        """
        # The legacy run_tick() method expects the full dataframe and the current equity
        actions = self.legacy_strategy.run_tick(ohlcv, self.engine.equity)
        return actions if actions else []
