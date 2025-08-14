# bots/execution.py
"""
Execution scaffolding for bot live-run (Phase 1 foundation).

Provides an ExecutionAdapter that translates strategy actions into
calls to the centralized TradeService.

Notes:
- Uses existing helpers to keep behavior consistent with AI/manual trades.
- Does not manage streaming here; a PriceFeed will be added separately.
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional
from decimal import Decimal
import logging
import uuid

from django.contrib.auth import get_user_model
from accounts.models import Account
from trades.services import TradeService
from trades.helpers import fetch_symbol_info_for_platform, fetch_live_price_for_platform
from trading.models import Trade
from trades.services import close_trade_globally, partially_close_trade

logger = logging.getLogger(__name__)
User = get_user_model()


class ExecutionAdapter:
    """
    Converts normalized strategy actions into calls to the central TradeService
    and related trade operations.
    """

    def __init__(self, user, default_symbol: Optional[str] = None, default_rr: float = 2.0, run_metadata: Optional[Dict[str, Any]] = None, max_open_positions: Optional[int] = None):
        self.user = user
        self.default_symbol = default_symbol
        try:
            self.default_rr = float(default_rr) if default_rr is not None else 2.0
        except Exception:
            self.default_rr = 2.0
        # Metadata passed from live loop: { 'live_run_id': ..., 'bot_version_id': ..., 'source': 'BOT' }
        self.run_metadata = run_metadata or {}
        # Max open positions allowed for this live run (from strategy params)
        self.max_open_positions = None
        try:
            self.max_open_positions = int(max_open_positions) if max_open_positions is not None else None
        except Exception:
            self.max_open_positions = None

    def _compute_stop_loss_distance(self, account: Account, symbol: str, direction: str, entry_price: Decimal, stop_loss_price: Decimal) -> int:
        symbol_info = fetch_symbol_info_for_platform(account, symbol)
        if not symbol_info or symbol_info.get("error"):
            raise ValueError(f"Could not fetch symbol info for {symbol}: {symbol_info.get('error') if symbol_info else 'Unknown error'}")
        pip_size = Decimal(str(symbol_info.get("pip_size")))
        if pip_size <= 0:
            raise ValueError(f"Invalid pip_size for {symbol}: {pip_size}")

        if direction.upper() == "BUY":
            sl_diff = entry_price - stop_loss_price
        else:  # SELL
            sl_diff = stop_loss_price - entry_price
        sl_diff = abs(sl_diff)
        distance = int(round(sl_diff / pip_size))
        return max(distance, 0)

    def _get_entry_price(self, account: Account, symbol: str, direction: str, limit_price: Optional[Decimal]) -> Decimal:
        """
        Use provided limit_price if given; else fetch live bid/ask and choose side-appropriate price.
        """
        if limit_price is not None:
            return Decimal(str(limit_price))
        price = fetch_live_price_for_platform(account, symbol)
        if price.get("error"):
            raise ValueError(price["error"])
        if direction.upper() == "BUY":
            # For BUY market orders, entry at ask
            return Decimal(str(price.get("ask")))
        else:
            # For SELL market orders, entry at bid
            return Decimal(str(price.get("bid")))

    def open_trade(
        self,
        account: Account,
        symbol: str,
        side: str,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        risk_percent: float = 0.3,
        reason: str = "",
        rr_ratio: Optional[float] = None,
        projected_profit: float = 0.0,
        projected_loss: float = 0.0,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build the same payload used by AI/manual execution and call TradeService.
        sl is required. If tp is None, derive a take-profit using RR multiple against SL distance.
        """
        if sl is None:
            raise ValueError("Stop-loss absolute price is required for OPEN_TRADE.")

        try:
            # Determine entry price
            entry_price = self._get_entry_price(account, symbol, side, Decimal(str(limit_price)) if limit_price is not None else None)

            # Compute SL distance in pips for validation, and price distance for RR
            stop_loss_distance = self._compute_stop_loss_distance(
                account=account,
                symbol=symbol,
                direction=side,
                entry_price=Decimal(str(entry_price)),
                stop_loss_price=Decimal(str(sl)),
            )
            price_sl_distance = abs(Decimal(str(entry_price)) - Decimal(str(sl)))

            # Derive take-profit if missing
            if tp is None:
                rr = float(rr_ratio) if rr_ratio is not None else self.default_rr
                if side.upper() == "BUY":
                    tp_price = Decimal(str(entry_price)) + Decimal(str(rr)) * price_sl_distance
                else:
                    tp_price = Decimal(str(entry_price)) - Decimal(str(rr)) * price_sl_distance
                tp = float(tp_price)
                logger.info(f"Derived TP using RR={rr}: entry={entry_price}, SL_dist={price_sl_distance} -> TP={tp}")

            payload = {
                "account_id": str(account.id),
                "symbol": symbol,
                "direction": side.upper(),
                "order_type": order_type.upper(),
                "limit_price": float(entry_price) if order_type.upper() != "MARKET" or limit_price is not None else None,
                "stop_loss_distance": stop_loss_distance,
                "take_profit": float(tp),  # absolute
                "risk_percent": float(risk_percent),
                "reason": reason or "",
                "rr_ratio": rr_ratio if rr_ratio is not None else self.default_rr,
                "projected_profit": float(projected_profit),
                "projected_loss": float(projected_loss),
            }
            # Attach run metadata and correlation id for tagging
            if self.run_metadata:
                payload.update({
                    "source": self.run_metadata.get("source", "BOT"),
                    "live_run_id": str(self.run_metadata.get("live_run_id")) if self.run_metadata.get("live_run_id") else None,
                    "bot_version_id": str(self.run_metadata.get("bot_version_id")) if self.run_metadata.get("bot_version_id") else None,
                })
            if correlation_id:
                payload["correlation_id"] = str(correlation_id)

            logger.info(f"ExecutionAdapter.open_trade payload: {payload}")
            svc = TradeService(self.user, payload)
            account_obj, final_lot, sl_price, tp_price = svc.validate()
            logger.info(f"TradeService.validate -> lot={final_lot}, sl_price={sl_price}, tp_price={tp_price}")
            resp = svc.execute_on_broker(account_obj, final_lot, sl_price, tp_price)
            logger.info(f"Broker response: {resp}")
            order, trade = svc.persist(account_obj, resp, final_lot, sl_price, tp_price)
            res = svc.build_response(order, trade)
            logger.info(f"Persisted order/trade -> response: {res}")
            return res
        except Exception as e:
            logger.error(f"open_trade failed: {e}", exc_info=True)
            raise

    def execute_actions(self, account: Account, actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for act in actions or []:
            try:
                action_type = (act.get("action") or "").upper()
                if action_type == "CLOSE_POSITION":
                    # Determine symbol, qty, and side/direction
                    d = act.get("details") if isinstance(act.get("details"), dict) else {}
                    symbol = d.get("symbol") or act.get("symbol") or act.get("instrument") or self.default_symbol
                    qty = d.get("qty") if d else act.get("qty")
                    # Infer side if provided to target long/short specifically
                    side = (d.get("direction") or d.get("side") or act.get("direction") or act.get("side") or "").upper()

                    if not symbol:
                        logger.warning(f"CLOSE_POSITION missing symbol; using default failed. action={act}")
                        continue

                    live_run_id = (self.run_metadata or {}).get("live_run_id")
                    if not live_run_id:
                        logger.warning(f"CLOSE_POSITION skipped: live_run_id missing in run_metadata; refusing to close unscoped trades. action={act}")
                        continue

                    qs = Trade.objects.filter(
                        account=account,
                        instrument=symbol,
                        trade_status="open",
                        live_run_id=live_run_id,
                    )
                    if side in ("BUY", "SELL"):
                        qs = qs.filter(direction=side)

                    qs = qs.order_by("-created_at")
                    if not qs.exists():
                        logger.info(f"No open trades to close for {symbol} (live_run={live_run_id}, side={side or 'ANY'}).")
                        continue

                    if qty in (None, "ALL", "all"):
                        count = 0
                        for t in qs:
                            try:
                                res = close_trade_globally(self.user, t.id)
                                results.append(res)
                                count += 1
                            except Exception as e:
                                logger.error(f"Failed to close trade {t.id}: {e}", exc_info=True)
                        logger.info(f"Closed {count} trade(s) for {symbol} (live_run={live_run_id}, side={side or 'ANY'}).")
                    else:
                        # Partial close the most recent matching trade
                        try:
                            target_trade = qs.first()
                            vol = Decimal(str(qty))
                            res = partially_close_trade(self.user, target_trade.id, vol)
                            results.append(res)
                            logger.info(f"Partially closed trade {target_trade.id} with qty {vol} for {symbol} (live_run={live_run_id}, side={side or 'ANY'}).")
                        except Exception as e:
                            logger.error(f"Partial close failed: {e} | action={act}", exc_info=True)
                    continue

                if action_type != "OPEN_TRADE":
                    logger.info(f"Skipping unsupported action: {action_type} | action={act}")
                    continue

                # Enforce max_open_positions per live_run before opening a new trade
                try:
                    live_run_id = (self.run_metadata or {}).get("live_run_id")
                    if self.max_open_positions is not None and live_run_id:
                        current_open = Trade.objects.filter(live_run_id=live_run_id, trade_status="open").count()
                        if current_open >= self.max_open_positions:
                            logger.info(f"Max open positions reached for live_run {live_run_id} (current={current_open}, max={self.max_open_positions}). Skipping OPEN_TRADE action: {act}")
                            continue
                except Exception as gate_e:
                    logger.warning(f"Failed to evaluate max_open_positions gate: {gate_e}")

                # Support both flat and legacy nested 'details'
                if "details" in act and isinstance(act["details"], dict):
                    d = act["details"]
                    symbol = d.get("symbol") or act.get("symbol") or self.default_symbol
                    side = d.get("direction") or act.get("side")
                    order_type = (d.get("order_type") or act.get("order_type") or "MARKET").upper()
                    limit_price = d.get("price") if order_type != "MARKET" else None
                    sl = d.get("stop_loss") if d.get("stop_loss") is not None else act.get("sl")
                    tp = d.get("take_profit") if d.get("take_profit") is not None else act.get("tp")
                    reason = d.get("comment") or act.get("tag") or act.get("reason") or ""
                    rr_ratio = d.get("rr_ratio") if d.get("rr_ratio") is not None else act.get("rr_ratio")
                else:
                    symbol = act.get("symbol") or act.get("instrument") or self.default_symbol
                    side = act.get("side") or act.get("direction")
                    order_type = (act.get("order_type") or "MARKET").upper()
                    limit_price = act.get("limit_price")
                    sl = act.get("sl")
                    tp = act.get("tp")
                    reason = act.get("tag") or act.get("reason") or ""
                    rr_ratio = act.get("rr_ratio")

                if not symbol or not side or sl is None:
                    logger.warning(f"Incomplete OPEN_TRADE action (missing symbol/side/sl): {act} | default_symbol={self.default_symbol}")
                    continue

                corr_id = act.get("correlation_id") or str(uuid.uuid4())
                res = self.open_trade(
                    account=account,
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    limit_price=limit_price,
                    sl=sl,
                    tp=tp,
                    risk_percent=float(act.get("risk_percent", 0.3)),
                    reason=reason,
                    rr_ratio=rr_ratio if rr_ratio is not None else self.default_rr,
                    projected_profit=act.get("projected_profit", 0.0),
                    projected_loss=act.get("projected_loss", 0.0),
                    correlation_id=corr_id,
                )
                results.append(res)
            except Exception as e:
                logger.error(f"Action execution failed: {e} | action={act}", exc_info=True)
        return results
