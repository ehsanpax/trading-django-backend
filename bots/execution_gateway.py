import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Any
<<<<<<< Updated upstream
import os
=======
>>>>>>> Stashed changes

from django.utils.crypto import get_random_string
from rest_framework.exceptions import ValidationError
from celery import current_app as celery_app
from django.conf import settings

from trades.services import TradeService
from trades.helpers import fetch_symbol_info_for_platform

logger = logging.getLogger(__name__)


def build_trade_request(
    *,
    account_id,
    symbol: str,
    direction: str,  # "BUY" | "SELL"
    order_type: str = "MARKET",  # "MARKET" | "LIMIT" | "STOP"
    limit_price: Optional[float] = None,
    # Either provide explicit distance OR provide prices so we compute it
    stop_loss_distance_pips: Optional[int] = None,
    take_profit_price: Optional[float] = None,
    risk_percent: float = 0.0,
    # Optional price inputs for conversion
    entry_price: Optional[float] = None,
    stop_loss_price: Optional[float] = None,
    # Optional metadata & projections
    metadata: Optional[Dict[str, Any]] = None,
    projections: Optional[Dict[str, float]] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a dict suitable for TradeService from the canonical execution intent.
    - Prefer explicit stop_loss_distance_pips; otherwise compute from entry_price & stop_loss_price using pip_size.
    - TP is absolute price.
    - risk_percent is percent (e.g. 1.0 for 1%).
    """
    projections = projections or {}

    # 1) Derive SL distance if not provided
    if stop_loss_distance_pips is None:
        if entry_price is None or stop_loss_price is None:
            raise ValidationError({
                "stop_loss": "Provide either stop_loss_distance_pips or both entry_price and stop_loss_price."
            })
        sym_info = fetch_symbol_info_for_platform(account_id, symbol)
        if not sym_info or sym_info.get("error"):
            raise ValidationError({"symbol": sym_info.get("error", "Could not fetch symbol info.")})
        pip_size = Decimal(str(sym_info.get("pip_size", "0.0001")))
        if pip_size == 0:
            raise ValidationError({"pip_size": "Invalid pip size (0)."})
        entry = Decimal(str(entry_price))
        sl_abs = Decimal(str(stop_loss_price))
        # distance is absolute price delta divided by pip size
        stop_loss_distance_pips = int(abs((entry - sl_abs) / pip_size).to_integral_value(rounding=ROUND_HALF_UP))

    # 2) Projections sanity
    projected_profit = projections.get("projected_profit", 0.0)
    projected_loss = projections.get("projected_loss", 0.0)
    rr_ratio = projections.get("rr_ratio")
    if rr_ratio is None:
        try:
            rr_ratio = (float(projected_profit) / abs(float(projected_loss))) if projected_loss else 0.0
        except Exception:
            rr_ratio = 0.0

    # 3) Build payload for TradeService
    payload = {
        "account_id": account_id,
        "symbol": symbol,
        "direction": direction,
        "order_type": order_type,
        "limit_price": Decimal(str(limit_price)) if limit_price is not None else None,
        "stop_loss_distance": int(stop_loss_distance_pips),
        "take_profit": Decimal(str(take_profit_price)) if take_profit_price is not None else None,
        "risk_percent": Decimal(str(risk_percent or 0)),
        # Defaults unless caller requests partial targets
        "partial_profit": False,
        "targets": [],
        # Projections (used for journaling/analytics and persisted on Order/Trade)
        "projected_profit": Decimal(str(projected_profit)),
        "projected_loss": Decimal(str(projected_loss)),
        "rr_ratio": Decimal(str(rr_ratio)),
        # Optional metadata
        "reason": (metadata or {}).get("reason", ""),
        # NOTE: idempotency is handled in later phases; keep key available for logging
        "_idempotency_key": idempotency_key or get_random_string(12),
        "_metadata": metadata or {},
    }
    return payload


class ExecutionGatewayLocal:
    """
    Local in-process execution gateway that wraps TradeService.
    Callers must pass an authenticated user (or a service principal in headless mode).
    """

    def __init__(self, user):
        self.user = user

    def _sanitize_for_celery(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Return a JSON-serializable copy of payload for Celery."""
        out: Dict[str, Any] = {}
        for k, v in payload.items():
            if k == "account_instance":
                # Never send Django model instances over Celery
                continue
            if isinstance(v, Decimal):
                out[k] = float(v)
            elif isinstance(v, (list, tuple)):
                new_list = []
                for item in v:
                    if isinstance(item, Decimal):
                        new_list.append(float(item))
                    else:
                        new_list.append(item)
                out[k] = new_list
            else:
                out[k] = v
        return out

    def execute(self, trade_request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute an OPEN_TRADE intent. By default, route to Celery task 'trades.tasks.execute_trade'
        so risk/ORM run in a prefork worker. If settings.EXECUTE_TRADES_INLINE is True,
        fallback to in-process execution (useful for tests/local).
        """
        logger.info(
            "ExecutionGatewayLocal.execute: %s %s on %s (acct=%s)",
            trade_request.get("order_type"),
            trade_request.get("direction"),
            trade_request.get("symbol"),
            trade_request.get("account_id"),
        )

        # Ensure DTO carries user_id for the worker
        dto = dict(trade_request)
        if "user_id" not in dto and hasattr(self.user, "id"):
            dto["user_id"] = str(self.user.id)

        use_inline = getattr(settings, "EXECUTE_TRADES_INLINE", False)
<<<<<<< Updated upstream
        # When running under pytest, prefer inline path to avoid external broker/result backends
        if not use_inline and os.environ.get("PYTEST_CURRENT_TEST"):
            use_inline = True
=======
>>>>>>> Stashed changes
        if not use_inline:
            try:
                sanitized = self._sanitize_for_celery(dto)
                async_result = celery_app.send_task(
                    "trades.tasks.execute_trade", args=[sanitized], kwargs={}, queue=getattr(settings, "TRADE_EXEC_QUEUE", "trade_exec")
                )
                result = async_result.get(timeout=getattr(settings, "TRADE_EXEC_TIMEOUT", 30))
                return result
            except Exception as e:
                logger.error("ExecutionGatewayLocal Celery submission failed: %s", e, exc_info=True)
                # Do NOT inline fallback in live bot context; surface an error to the caller
                raise ValidationError({"detail": "Trade dispatch failed; will not execute inline in async context.", "error": str(e)})

        # Inline path (tests/local)
        try:
            svc = TradeService(self.user, trade_request)
            account, final_lot, sl, tp = svc.validate()
            logger.info(
                "ExecutionGatewayLocal.validate -> lot=%s sl=%s tp=%s", str(final_lot), str(sl), str(tp)
            )
            resp = svc.execute_on_broker(account, final_lot, sl, tp)
            try:
                resp_preview = {k: resp.get(k) for k in list(resp.keys())[:6]} if isinstance(resp, dict) else resp
            except Exception:
                resp_preview = resp
            logger.info("ExecutionGatewayLocal.broker_resp: %s", resp_preview)
            order, trade = svc.persist(account, resp, final_lot, sl, tp)
            out = svc.build_response(order, trade)
            out["idempotency_key"] = trade_request.get("_idempotency_key")
            return out
        except ValidationError:
            raise
        except Exception as e:
            logger.error("ExecutionGatewayLocal error: %s", e, exc_info=True)
            raise ValidationError({"detail": str(e)})
