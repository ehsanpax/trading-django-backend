from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class Issue:
    path: str  # JSONPath-like, e.g. "entry.conditions[0].lhs"
    code: str  # machine-readable code, e.g. "indicator.unknown", "operator.unsupported"
    message: str  # human readable
    level: str = "error"  # error | warning | info


SUPPORTED_OPERATORS = {
    "<", "<=", ">", ">=", "==", "!=",
    "cross_over", "cross_under", "between", "in", "not_in",
}


class SectionedSpecValidator:
    def __init__(self, indicator_catalog: Optional[Dict[str, Any]] = None):
        # indicator_catalog example shape:
        # { "rsi": {"outputs": ["value"], "params": {"period": {"type": "int", "min": 1, "max": 1000}}, "timeframes": ["M1","M5",...] } }
        self.indicator_catalog = indicator_catalog or {}

    def validate(self, spec: Dict[str, Any]) -> List[Issue]:
        # Unwrap if given a wrapper object containing 'sectioned_spec'
        if isinstance(spec, dict) and isinstance(spec.get('sectioned_spec'), dict):
            spec = spec['sectioned_spec']

        issues: List[Issue] = []
        if not isinstance(spec, dict):
            return [Issue(path="", code="spec.type", message="Spec must be an object")]

        # Basic required sections (support long/short aliases)
        has_entry = ('entry' in spec) or ('entry_long' in spec or 'entry_short' in spec)
        has_exit = ('exit' in spec) or ('exit_long' in spec or 'exit_short' in spec)
        if not has_entry:
            issues.append(Issue(path="entry", code="section.missing", message="Missing 'entry' section"))
        if not has_exit:
            issues.append(Issue(path="exit", code="section.missing", message="Missing 'exit' section"))
        if 'risk' not in spec:
            issues.append(Issue(path="risk", code="section.missing", message="Missing 'risk' section"))

        # Validate indicators block (optional)
        indicators = spec.get("indicators") or []
        if not isinstance(indicators, list):
            issues.append(Issue(path="indicators", code="indicators.type", message="'indicators' must be a list"))
        else:
            issues += self._validate_indicators(indicators)

        # Validate entry/exit conditions across possible sections
        for name in ("entry", "exit", "entry_long", "entry_short", "exit_long", "exit_short"):
            if isinstance(spec.get(name), dict):
                issues += self._validate_section_conditions(spec.get(name), prefix=name)

        # Validate risk
        issues += self._validate_risk(spec.get("risk") or {}, prefix="risk")

        # Compute warmup suggestion (max period across indicators)
        warmup = self.suggest_warmup_bars(spec)
        if warmup is not None and warmup > 0:
            issues.append(Issue(path="", code="warmup.suggest", message=f"Suggested warmup bars: {warmup}", level="info"))

        return issues

    def _validate_indicators(self, indicators: List[Dict[str, Any]]) -> List[Issue]:
        issues: List[Issue] = []
        names_seen = set()
        for i, ind in enumerate(indicators):
            path = f"indicators[{i}]"
            name = (ind or {}).get("name")
            if not name or not isinstance(name, str):
                issues.append(Issue(path=f"{path}.name", code="indicator.name", message="Indicator name is required"))
                continue
            if name in names_seen:
                issues.append(Issue(path=f"{path}.name", code="indicator.duplicate", message=f"Duplicate indicator '{name}'"))
            names_seen.add(name)
            catalog = self.indicator_catalog.get(name)
            if not catalog:
                issues.append(Issue(path=f"{path}.name", code="indicator.unknown", message=f"Unknown indicator '{name}'"))
                continue
            # timeframe
            tf = ind.get("timeframe") or catalog.get("default_timeframe")
            tfs = catalog.get("timeframes") or []
            if tfs and tf not in tfs:
                issues.append(Issue(path=f"{path}.timeframe", code="indicator.timeframe", message=f"Timeframe '{tf}' not supported for '{name}'"))
            # params
            params = ind.get("params") or {}
            issues += self._validate_indicator_params(name, params, catalog, path)
            # outputs
            outputs = ind.get("outputs") or catalog.get("outputs") or []
            if not outputs:
                issues.append(Issue(path=f"{path}.outputs", code="indicator.outputs", message=f"No outputs defined for '{name}'"))
        return issues

    def _validate_indicator_params(self, name: str, params: Dict[str, Any], catalog: Dict[str, Any], path: str) -> List[Issue]:
        issues: List[Issue] = []
        schema = catalog.get("params") or {}
        # Unknown params
        for k in params.keys():
            if k not in schema:
                issues.append(Issue(path=f"{path}.params.{k}", code="param.unknown", message=f"Unknown param for '{name}': {k}"))
        # Required + type/bounds
        for p, meta in schema.items():
            if meta.get("required") and p not in params:
                issues.append(Issue(path=f"{path}.params.{p}", code="param.required", message=f"Missing required param '{p}' for '{name}'"))
                continue
            if p in params:
                val = params[p]
                ptype = meta.get("type")
                if ptype == "int" and not isinstance(val, int):
                    issues.append(Issue(path=f"{path}.params.{p}", code="param.type", message=f"Param '{p}' must be int"))
                if ptype == "float" and not isinstance(val, (int, float)):
                    issues.append(Issue(path=f"{path}.params.{p}", code="param.type", message=f"Param '{p}' must be float"))
                if "min" in meta and isinstance(val, (int, float)) and val < meta["min"]:
                    issues.append(Issue(path=f"{path}.params.{p}", code="param.min", message=f"Param '{p}' must be >= {meta['min']}"))
                if "max" in meta and isinstance(val, (int, float)) and val > meta["max"]:
                    issues.append(Issue(path=f"{path}.params.{p}", code="param.max", message=f"Param '{p}' must be <= {meta['max']}"))
        return issues

    def _validate_section_conditions(self, sec: Optional[Dict[str, Any]], prefix: str) -> List[Issue]:
        if not sec:
            return []
        issues: List[Issue] = []
        conds = sec.get("conditions") or []
        if not isinstance(conds, list):
            issues.append(Issue(path=f"{prefix}.conditions", code="conditions.type", message="'conditions' must be a list"))
            return issues
        for i, c in enumerate(conds):
            path = f"{prefix}.conditions[{i}]"
            lhs = (c or {}).get("lhs")
            op = (c or {}).get("op")
            rhs = (c or {}).get("rhs")
            # Operator support
            if op not in SUPPORTED_OPERATORS:
                issues.append(Issue(path=f"{path}.op", code="operator.unsupported", message=f"Unsupported operator '{op}'"))
            # LHS/RHS references
            issues += self._validate_operand(lhs, f"{path}.lhs")
            issues += self._validate_operand(rhs, f"{path}.rhs")
        # Optional: filters
        filters = sec.get("filters") or []
        if not isinstance(filters, list):
            issues.append(Issue(path=f"{prefix}.filters", code="filters.type", message="'filters' must be a list"))
        else:
            for i, f in enumerate(filters):
                fpath = f"{prefix}.filters[{i}]"
                name = (f or {}).get("name")
                if not name:
                    issues.append(Issue(path=f"{fpath}.name", code="filter.name", message="Filter name is required"))
        return issues

    def _validate_operand(self, operand: Any, path: str) -> List[Issue]:
        # Operand can be a literal (number/bool), price field, or indicator ref: { ind: "rsi", output: "value" }
        issues: List[Issue] = []
        if isinstance(operand, (int, float, bool)):
            return issues
        if isinstance(operand, dict):
            if "ind" in operand:
                ind_name = operand.get("ind")
                out = operand.get("output") or "value"
                catalog = self.indicator_catalog.get(ind_name)
                if not catalog:
                    issues.append(Issue(path=path, code="indicator.ref.unknown", message=f"Unknown indicator ref '{ind_name}'"))
                else:
                    outputs = catalog.get("outputs") or []
                    if outputs and out not in outputs:
                        issues.append(Issue(path=path, code="indicator.output.unknown", message=f"Unknown output '{out}' for indicator '{ind_name}'"))
            elif "price" in operand:
                field = operand.get("price")
                if field not in {"open","high","low","close","volume"}:
                    issues.append(Issue(path=path, code="price.field", message=f"Unknown price field '{field}'"))
            else:
                issues.append(Issue(path=path, code="operand.shape", message="Operand object must contain 'ind' or 'price'"))
            return issues
        # strings are not supported unless explicitly defined (e.g., session names)
        issues.append(Issue(path=path, code="operand.type", message="Operand must be number or object"))
        return issues

    def _validate_risk(self, risk: Dict[str, Any], prefix: str) -> List[Issue]:
        issues: List[Issue] = []
        sizing = risk.get("sizing") or {}
        if sizing:
            mode = sizing.get("mode")
            if mode not in {"fixed_amount","fixed_risk_pct","fixed_lots"}:
                issues.append(Issue(path=f"{prefix}.sizing.mode", code="risk.sizing.mode", message="Unsupported sizing.mode"))
            amt = sizing.get("amount")
            if mode == "fixed_amount" and (not isinstance(amt, (int,float)) or amt <= 0):
                issues.append(Issue(path=f"{prefix}.sizing.amount", code="risk.sizing.amount", message="amount must be > 0"))
            rp = sizing.get("risk_pct")
            if mode == "fixed_risk_pct" and (not isinstance(rp, (int,float)) or not (0 < rp <= 100)):
                issues.append(Issue(path=f"{prefix}.sizing.risk_pct", code="risk.sizing.risk_pct", message="risk_pct must be in (0,100]"))
        sl = risk.get("stop_loss")
        if sl is not None and not isinstance(sl, (int,float)):
            issues.append(Issue(path=f"{prefix}.stop_loss", code="risk.stop_loss", message="stop_loss must be number (pips/pts)"))
        tp = risk.get("take_profit")
        if tp is not None and not isinstance(tp, (int,float)):
            issues.append(Issue(path=f"{prefix}.take_profit", code="risk.take_profit", message="take_profit must be number (pips/pts)"))
        mc = risk.get("max_concurrent_positions")
        if mc is not None and (not isinstance(mc, int) or mc < 1):
            issues.append(Issue(path=f"{prefix}.max_concurrent_positions", code="risk.max_concurrent_positions", message="must be int >= 1"))
        return issues

    def suggest_warmup_bars(self, spec: Dict[str, Any]) -> Optional[int]:
        max_period = 0
        for ind in (spec.get("indicators") or []):
            params = ind.get("params") or {}
            period = params.get("period") or params.get("length") or 0
            try:
                max_period = max(max_period, int(period))
            except Exception:
                continue
        return max_period if max_period > 0 else None


def validate_sectioned_spec(spec: Dict[str, Any], indicator_catalog: Optional[Dict[str, Any]] = None) -> List[Issue]:
    return SectionedSpecValidator(indicator_catalog=indicator_catalog).validate(spec)
