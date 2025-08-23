import pandas as pd
from pydantic import BaseModel, Field
from typing import List, Dict, Any
from decimal import Decimal

from bots.base import BaseStrategy, make_open_trade, make_close_position, make_reduce_position
from core.interfaces import IndicatorRequest
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)

class SectionedStrategySpec(BaseModel):
    """
    Pydantic model for validating the sectioned strategy specification.
    """
    entry_long: dict = None
    entry_short: dict = None
    exit_long: dict = None
    exit_short: dict = None
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

        # This ensures the _calculate_indicators method in BaseStrategy works correctly.
        reqs = self.required_indicators()
        # Normalize indicator names to lowercase to match registry keys and column naming
        self.REQUIRED_INDICATORS = [{"name": r.name.lower(), "params": r.params} for r in reqs]
        
        # --- Fix: Also populate a list of the final column names for easy access later ---
        self.indicator_column_names = []
        from core.registry import indicator_registry
        for r in reqs:
            try:
                indicator_cls = indicator_registry.get_indicator(r.name.lower())
                indicator_instance = indicator_cls()
                # Use all defined outputs for multi-output indicators (e.g., DMI: plus_di, minus_di, adx)
                outputs = getattr(indicator_instance, 'OUTPUTS', []) or []
                if outputs:
                    for output_name in outputs:
                        param_str = "_".join([f"{k}_{v}" for k, v in sorted(r.params.items())])
                        column_name = f"{r.name.lower()}_{str(output_name).lower()}_{param_str}".lower()
                        self.indicator_column_names.append(column_name)
                else:
                    logger.warning(f"Indicator '{r.name}' has no defined OUTPUTS.")
            except Exception as e:
                logger.warning(f"Could not generate column name for indicator {r.name}: {e}")
        # Deduplicate any repeated column names
        self.indicator_column_names = list(dict.fromkeys(self.indicator_column_names))
        # --- End Fix ---

        # Tracing controls (opt-in). Frontend/API can toggle later.
        self._trace_enabled: bool = bool(strategy_params.get('trace_enabled', False))
        self._trace_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self._trace_sampling: int = int(strategy_params.get('trace_sampling', 1) or 1)
        self._trace_counter: int = 0

    # --- Tracing API ---
    def set_trace(self, enabled: bool = True, callback: Optional[Callable[[Dict[str, Any]], None]] = None, sampling: int = 1):
        self._trace_enabled = enabled
        self._trace_callback = callback
        self._trace_sampling = max(1, int(sampling or 1))

    def _emit_trace(self, section: str, kind: str, payload: Dict[str, Any], df_current_window: Optional[pd.DataFrame] = None):
        if not self._trace_enabled or not self._trace_callback:
            return
        self._trace_counter += 1
        if (self._trace_counter % self._trace_sampling) != 0:
            return
        ts = None
        bar_index = None
        try:
            if df_current_window is not None and len(df_current_window.index) > 0:
                ts = pd.Timestamp(df_current_window.index[-1]).to_pydatetime()
                bar_index = len(df_current_window) - 1
        except Exception:
            pass
        atom = {
            'section': section,
            'kind': kind,
            'ts': ts.isoformat() if ts else None,
            'bar_index': bar_index,
            'payload': payload,
        }
        try:
            self._trace_callback(atom)
        except Exception:
            logger.debug('Trace callback failed', exc_info=True)

    def required_indicators(self) -> List[IndicatorRequest]:
        """
        Scans the entry, exit, and risk conditions in the spec to determine which indicators are needed.
        """
        required = set()

        def walk_conditions(node):
            if isinstance(node, dict):
                if node.get("type") == "indicator":
                    # Normalize to lowercase to match registry keys
                    name = node["name"].lower()
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

        if self.spec.entry_long:
            walk_conditions(self.spec.entry_long)
        if self.spec.entry_short:
            walk_conditions(self.spec.entry_short)
        if self.spec.exit_long:
            walk_conditions(self.spec.exit_long)
        if self.spec.exit_short:
            walk_conditions(self.spec.exit_short)
        
        # Check for ATR in risk settings for SL
        if self.spec.risk and self.spec.risk.get('sl', {}).get('type') == 'atr':
            required.add(('atr', frozenset({'length': 14}.items()))) # Assuming default ATR length 14

        walk_conditions(self.spec.risk)
        
        # Merge indicator PARAMS_SCHEMA defaults into each required indicator's params
        indicator_requests: List[IndicatorRequest] = []
        try:
            from core.registry import indicator_registry
            for name, params in required:
                params_dict = dict(params)
                try:
                    ind_cls = indicator_registry.get_indicator(name)
                    schema = getattr(ind_cls, 'PARAMS_SCHEMA', {}) or {}
                    default_params: Dict[str, Any] = {}
                    for p_name, p_schema in schema.items():
                        if p_schema is None:
                            continue
                        default_val = p_schema.get('default')
                        if default_val is not None:
                            default_params[p_name] = default_val
                    # Explicit params override defaults
                    merged = {**default_params, **params_dict}
                    indicator_requests.append(IndicatorRequest(name=name, params=merged))
                except Exception:
                    # Fall back to provided params if any registry/schema issue occurs
                    indicator_requests.append(IndicatorRequest(name=name, params=params_dict))
        except Exception:
            # If registry import fails, fall back to raw params
            indicator_requests = [IndicatorRequest(name=name, params=dict(params)) for name, params in required]
        
        # Deduplicate after defaults merge
        unique_keys = set()
        unique_requests: List[IndicatorRequest] = []
        for req in indicator_requests:
            key = (req.name, frozenset(req.params.items()))
            if key not in unique_keys:
                unique_keys.add(key)
                unique_requests.append(req)
        indicator_requests = unique_requests

        logger.info(f"Discovered required indicators: {indicator_requests}")
        return indicator_requests

    def run_tick(self, df_current_window: pd.DataFrame, account_equity: float) -> List[Dict[str, Any]]:
        """
        Evaluates the entry and exit conditions based on the pre-computed indicator data
        and emits actions. This method is pure and does not perform any fills.
        """
        actions = []
        # Emit a minimal inputs snapshot (price only) for context
        try:
            self._emit_trace('engine', 'inputs', {
                'close': float(df_current_window.iloc[-1]['close']),
            }, df_current_window)
        except Exception:
            pass
        
        def _create_trade_action(direction: str):
            risk_params = self.spec.risk
            sl_config = risk_params.get("sl", {})
            tp_pips = risk_params.get("take_profit_pips")
            current_price = df_current_window.iloc[-1]['close']
            sl = None

            if sl_config.get("type") == "atr":
                atr_params = {'length': 14} # Assuming default ATR length 14
                param_str = "_".join([f"{k}_{v}" for k, v in sorted(atr_params.items())])
                atr_col_name = f"atr_atr_{param_str}"
                
                if atr_col_name not in df_current_window.columns:
                    logger.error(f"ATR column '{atr_col_name}' not found in DataFrame.")
                    return None

                atr_val = df_current_window.iloc[-1][atr_col_name]
                sl_mult = sl_config.get("mult", 1.5)
                sl_offset = atr_val * sl_mult
                if direction == "BUY":
                    sl = current_price - sl_offset
                else: # SELL
                    sl = current_price + sl_offset
            elif sl_config.get("type") == "pct":
                sl_pct = sl_config.get("value", 0.01) # Default 1%
                if direction == "BUY":
                    sl = current_price * (1 - sl_pct)
                else: # SELL
                    sl = current_price * (1 + sl_pct)

            tp = None
            if tp_pips:
                if direction == "BUY":
                    tp = current_price + tp_pips * 0.0001
                else: # SELL
                    tp = current_price - tp_pips * 0.0001
            
            # --- Dynamic Position Sizing ---
            risk_pct = risk_params.get("risk_pct", 0.01) # Default 1% risk
            sl_distance = abs(current_price - sl) if sl else 0
            
            if sl_distance > 0 and self.instrument_spec:
                tick_size = Decimal(str(getattr(self.instrument_spec, 'tick_size', '0.00001')))
                tick_value = Decimal(str(getattr(self.instrument_spec, 'tick_value', '1.0')))
                contract_size = Decimal(str(getattr(self.instrument_spec, 'contract_size', '1.0')))
                
                sl_ticks = Decimal(str(sl_distance)) / tick_size
                risk_per_lot = sl_ticks * tick_value * contract_size
                
                if risk_per_lot > 0:
                    total_risk_amount = Decimal(str(account_equity)) * Decimal(str(risk_pct))
                    qty = float(total_risk_amount / risk_per_lot)
                else:
                    qty = risk_params.get("fixed_lot_size", 1.0)
            else:
                qty = risk_params.get("fixed_lot_size", 1.0) # Fallback to fixed size

            return make_open_trade(side=direction, qty=qty, sl=sl, tp=tp, tag=f"Entry {direction}", risk_percent=risk_pct)

        # --- Evaluate Entry Conditions ---
        if self.spec.entry_long:
            try:
                long_ok = self._evaluate_condition(self.spec.entry_long, df_current_window)
                self._emit_trace('entry', 'condition_eval', {'side': 'LONG', 'result': bool(long_ok)}, df_current_window)
                if long_ok:
                    act = _create_trade_action("BUY")
                    if act:
                        actions.append(act)
                        self._emit_trace('entry', 'order_intent', {'side': 'BUY', 'qty': act.get('qty')}, df_current_window)
            except Exception as e:
                logger.error(f"Error evaluating long entry condition: {e}", exc_info=True)

        if self.spec.entry_short:
            try:
                short_ok = self._evaluate_condition(self.spec.entry_short, df_current_window)
                self._emit_trace('entry', 'condition_eval', {'side': 'SHORT', 'result': bool(short_ok)}, df_current_window)
                if short_ok:
                    act = _create_trade_action("SELL")
                    if act:
                        actions.append(act)
                        self._emit_trace('entry', 'order_intent', {'side': 'SELL', 'qty': act.get('qty')}, df_current_window)
            except Exception as e:
                logger.error(f"Error evaluating short entry condition: {e}", exc_info=True)

        # --- Evaluate Exit Conditions ---
        if self.spec.exit_long:
            try:
                exit_long = self._evaluate_condition(self.spec.exit_long, df_current_window)
                self._emit_trace('exit', 'condition_eval', {'side': 'LONG', 'result': bool(exit_long)}, df_current_window)
                if exit_long:
                    actions.append(make_close_position(side="BUY", qty="ALL", tag="Exit Long"))
                    self._emit_trace('exit', 'order_intent', {'side': 'BUY', 'qty': 'ALL'}, df_current_window)
            except Exception as e:
                logger.error(f"Error evaluating long exit condition: {e}", exc_info=True)
        
        if self.spec.exit_short:
            try:
                exit_short = self._evaluate_condition(self.spec.exit_short, df_current_window)
                self._emit_trace('exit', 'condition_eval', {'side': 'SHORT', 'result': bool(exit_short)}, df_current_window)
                if exit_short:
                    actions.append(make_close_position(side="SELL", qty="ALL", tag="Exit Short"))
                    self._emit_trace('exit', 'order_intent', {'side': 'SELL', 'qty': 'ALL'}, df_current_window)
            except Exception as e:
                logger.error(f"Error evaluating short exit condition: {e}", exc_info=True)
            
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
                right_series = right_val
            elif isinstance(right_val, (int, float)) and hasattr(left_val, 'iloc'):
                right_series = pd.Series([right_val] * len(left_val), index=left_val.index)
                left_series = left_val
            else:
                logger.error(f"Incompatible types for comparison: {type(left_val)} and {type(right_val)}")
                return False
        else:
            left_series = left_val
            right_series = right_val

        if comparison_op in ["crosses_above", "crossesabove", "cross_above"]:
            return left_series.iloc[-2] < right_series.iloc[-2] and left_series.iloc[-1] > right_series.iloc[-1]
        elif comparison_op in ["crosses_below", "crossesbelow", "cross_below"]:
            return left_series.iloc[-2] > right_series.iloc[-2] and left_series.iloc[-1] < right_series.iloc[-1]
        elif comparison_op in [">", "greater_than"]:
            return left_series.iloc[-1] > right_series.iloc[-1]
        elif comparison_op in ["<", "less_than"]:
            return left_series.iloc[-1] < right_series.iloc[-1]
        
        raise ValueError(f"Unsupported operator: {comparison_op}")

    def _get_value(self, operand: dict | str | int | float, df: pd.DataFrame) -> pd.Series | float:
        """
        Resolves an operand to either a DataFrame series or a literal value.
        This method is designed to be resilient to different indicator column naming conventions.
        """
        if isinstance(operand, (int, float)):
            return operand
        if isinstance(operand, str):  # e.g., "close"
            return df[operand]
        
        if isinstance(operand, dict):
            operand_type = operand.get("type")
            if operand_type == "indicator":
                name = operand["name"].lower()
                params = operand.get("params", {})

                # Merge PARAMS_SCHEMA defaults so lookup uses the same params as computation
                try:
                    from core.registry import indicator_registry
                    ind_cls = indicator_registry.get_indicator(name)
                    schema = getattr(ind_cls, 'PARAMS_SCHEMA', {}) or {}
                    default_params: Dict[str, Any] = {}
                    for p_name, p_schema in schema.items():
                        if p_schema is None:
                            continue
                        default_val = p_schema.get('default')
                        if default_val is not None and p_name not in params:
                            default_params[p_name] = default_val
                    params = {**default_params, **params}
                except Exception:
                    # If anything fails, continue with provided params only
                    pass

                param_str = "_".join([f"{k}_{v}" for k, v in sorted(params.items())])

                # Convention 1: Output defaults to the indicator's name (e.g., 'ema_ema_...').
                output_as_name = (operand.get("output") or name).lower()
                column_name_v1 = f"{name}_{output_as_name}_{param_str}"
                if column_name_v1 in df.columns:
                    return df[column_name_v1]

                # Convention 2 (Fallback): Output defaults to 'default' (e.g., 'price_default_...').
                output_as_default = (operand.get("output") or "default").lower()
                column_name_v2 = f"{name}_{output_as_default}_{param_str}"
                if column_name_v2 in df.columns:
                    return df[column_name_v2]
                
                # If neither convention finds a column, raise an error.
                raise ValueError(
                    f"Indicator column for '{name}' with params {params} not found. "
                    f"Tried '{column_name_v1}' and '{column_name_v2}'. "
                    f"Available columns: {df.columns.tolist()}"
                )

            elif operand_type == "literal":
                return operand.get("value")

        raise ValueError(f"Unsupported operand type: {operand}")

    def get_min_bars_needed(self, buffer_bars: int = 10) -> int:
        """
        Estimate the minimum bars required from the spec's indicators.
        Uses the largest 'length' (or 'period') of required indicators, plus a safety buffer.
        Defaults to 50 if nothing found.
        """
        try:
            reqs: List[IndicatorRequest] = self.required_indicators()
        except Exception:
            return 50 + buffer_bars

        max_len = 0
        for r in reqs:
            params = r.params or {}
            # Common keys across EMA/SMA/ATR/etc.
            for k in ("length", "period", "window"):
                if k in params and isinstance(params[k], (int, float)):
                    max_len = max(max_len, int(params[k]))
        base = max(50, max_len)
        return int(base + max(0, buffer_bars))
