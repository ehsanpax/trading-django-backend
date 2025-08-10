import pandas as pd
from pydantic import BaseModel, Field
from typing import List, Dict, Any

from bots.base import BaseStrategy, make_open_trade, make_close_position, make_reduce_position
from core.interfaces import IndicatorRequest
import logging

logger = logging.getLogger(__name__)

class SectionedStrategySpec(BaseModel):
    """
    Pydantic model for validating the sectioned strategy specification.
    """
    entry: dict
    exit: dict
    filters: dict = Field(default_factory=dict)
    risk: dict

class SectionedStrategy(BaseStrategy):
    """
    A strategy adapter that executes a strategy defined by a sectioned JSON spec.
    """
    NAME = "SECTIONED_SPEC"
    DISPLAY_NAME = "Sectioned Strategy"

    def __init__(self, instrument_symbol: str, account_id: str, instrument_spec: Any, strategy_params: Dict[str, Any], indicator_params: Dict[str, Any], risk_settings: Dict[str, Any]):
        super().__init__(instrument_symbol, account_id, instrument_spec, strategy_params, indicator_params, risk_settings)
        
        # The raw spec is expected to be in strategy_params under a specific key
        raw_spec = strategy_params.get("sectioned_spec", {})
        self.spec = SectionedStrategySpec(**raw_spec)
        
        # The risk and filters configs are also passed in strategy_params
        self.risk_config = strategy_params.get("risk", {})
        self.filters_config = strategy_params.get("filters", {})

        # --- Fix: Populate self.REQUIRED_INDICATORS for the base class ---
        # This ensures the _calculate_indicators method in BaseStrategy works correctly.
        reqs = self.required_indicators()
        self.REQUIRED_INDICATORS = [{"name": r.name, "params": r.params} for r in reqs]
        # --- End Fix ---

    def required_indicators(self) -> List[IndicatorRequest]:
        """
        Scans the entry, exit, and risk conditions in the spec to determine which indicators are needed.
        """
        required = set()

        def walk_conditions(node):
            if isinstance(node, dict):
                if node.get("type") == "indicator":
                    name = node["name"]
                    params = node.get("params", {})
                    frozen_params = frozenset(params.items())
                    required.add((name, frozen_params))
                
                # Recursively walk through clauses and other nested structures
                if "clauses" in node:
                    for clause in node["clauses"]:
                        walk_conditions(clause)
                if "lhs" in node:
                    walk_conditions(node["lhs"])
                if "rhs" in node:
                    walk_conditions(node["rhs"])

            elif isinstance(node, list):
                for item in node:
                    walk_conditions(item)

        walk_conditions(self.spec.entry)
        walk_conditions(self.spec.exit)
        walk_conditions(self.spec.risk)
        
        indicator_requests = [IndicatorRequest(name=name, params=dict(params)) for name, params in required]
        
        logger.info(f"Discovered required indicators: {indicator_requests}")
        return indicator_requests

    def run_tick(self, df_current_window: pd.DataFrame, account_equity: float) -> List[Dict[str, Any]]:
        """
        Evaluates the entry and exit conditions based on the pre-computed indicator data
        and emits actions. This method is pure and does not perform any fills.
        """
        actions = []
        
        # --- Evaluate Entry Conditions ---
        if self.spec.entry:
            try:
                entry_signal = self._evaluate_condition(self.spec.entry, df_current_window)
                if entry_signal:
                    risk_params = self.spec.risk
                    # TODO: A more robust sizing and SL/TP calculation is needed.
                    qty = risk_params.get("fixed_lot_size", 1.0)
                    sl_pips = risk_params.get("stop_loss_pips")
                    tp_pips = risk_params.get("take_profit_pips")
                    
                    # This is a simplified SL/TP calculation. A real one would use tick_size.
                    current_price = df_current_window.iloc[-1]['close']
                    sl = current_price - sl_pips * 0.0001 if sl_pips else None
                    tp = current_price + tp_pips * 0.0001 if tp_pips else None

                    actions.append(make_open_trade(side="BUY", qty=qty, sl=sl, tp=tp, tag="Entry Signal"))
            except Exception as e:
                logger.error(f"Error evaluating entry condition: {e}", exc_info=True)

        # --- Evaluate Exit Conditions ---
        if self.spec.exit:
            try:
                exit_signal = self._evaluate_condition(self.spec.exit, df_current_window)
                if exit_signal:
                    actions.append(make_close_position(side="ANY", qty="ALL", tag="Exit Signal"))
            except Exception as e:
                logger.error(f"Error evaluating exit condition: {e}", exc_info=True)
            
        return actions

    def _evaluate_condition(self, condition: dict, df: pd.DataFrame) -> bool:
        """
        A simple recursive evaluator for the condition logic.
        Supports 'and', 'or', and basic comparisons.
        """
        op = condition.get("op")
        if op in ["AND", "OR"]:
            clauses = condition.get("clauses", [])
            if op == "AND":
                return all(self._evaluate_condition(sub, df) for sub in clauses)
            elif op == "OR":
                return any(self._evaluate_condition(sub, df) for sub in clauses)

        # Base case: a single comparison
        if "lhs" not in condition or "rhs" not in condition:
            logger.warning(f"Invalid condition format, missing 'lhs' or 'rhs': {condition}")
            return False

        left_val = self._get_value(condition["lhs"], df)
        right_val = self._get_value(condition["rhs"], df)
        
        comparison_op = condition.get("op")

        # Ensure left_val and right_val are comparable
        if not hasattr(left_val, 'iloc') or not hasattr(right_val, 'iloc'):
             # Handle cases where one of the values is a literal
            if isinstance(left_val, (int, float)) and hasattr(right_val, 'iloc'):
                left_series = pd.Series([left_val] * len(right_val), index=right_val.index)
            elif isinstance(right_val, (int, float)) and hasattr(left_val, 'iloc'):
                right_series = pd.Series([right_val] * len(left_val), index=left_val.index)
            else:
                logger.error(f"Incompatible types for comparison: {type(left_val)} and {type(right_val)}")
                return False
        else:
            left_series = left_val
            right_series = right_val

        if comparison_op == "crosses_above":
            return left_series.iloc[-2] < right_series.iloc[-2] and left_series.iloc[-1] > right_series.iloc[-1]
        elif comparison_op == "crosses_below":
            return left_series.iloc[-2] > right_series.iloc[-2] and left_series.iloc[-1] < right_series.iloc[-1]
        elif comparison_op == ">":
            return left_series.iloc[-1] > right_series.iloc[-1]
        elif comparison_op == "<":
            return left_series.iloc[-1] < right_series.iloc[-1]
        
        raise ValueError(f"Unsupported operator: {comparison_op}")

    def _get_value(self, operand: dict | str | int | float, df: pd.DataFrame) -> pd.Series | float:
        """
        Resolves an operand to either a DataFrame series or a literal value.
        """
        if isinstance(operand, (int, float)):
            return operand
        if isinstance(operand, str):  # e.g., "close"
            return df[operand]
        
        if isinstance(operand, dict):
            operand_type = operand.get("type")
            if operand_type == "indicator":
                name = operand["name"]
                params = operand.get("params", {})
                # Default output name is the indicator name in lowercase, e.g., 'ema' for 'EMA'
                output = operand.get("output", name.lower())
                param_str = "_".join([f"{k}_{v}" for k, v in sorted(params.items())])
                column_name = f"{name}_{output}_{param_str}"
                if column_name not in df.columns:
                    raise ValueError(f"Indicator column '{column_name}' not found in DataFrame. Available: {df.columns.tolist()}")
                return df[column_name]
            elif operand_type == "literal":
                return operand.get("value")

        raise ValueError(f"Unsupported operand type: {operand}")

    def get_min_bars_needed(self, buffer_bars: int = 10) -> int:
        """
        Calculates the minimum number of bars required for the strategy.
        This should be derived from the indicators required by the spec.
        """
        # TODO: Calculate this based on the actual required indicators' min_bars.
        # For now, returning a safe default.
        return 50 # Placeholder
