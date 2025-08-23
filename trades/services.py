# trades/services.py
import logging
from django.conf import settings
from decimal import Decimal
from django.shortcuts import get_object_or_404
from accounts.models import Account
from risk.management import (
    validate_trade_request,
    perform_risk_checks,
    fetch_risk_settings,
)
from trading.models import Order, Trade, ProfitTarget
from uuid import uuid4
from .targets import derive_target_price
from trading.models import IndicatorData
from rest_framework.exceptions import ValidationError, APIException, PermissionDenied
from .exceptions import (
    BrokerAPIError,
    BrokerConnectionError,
    TradeValidationError,
    TradeSyncError,
)
from django.utils import timezone as django_timezone  # Alias for django's timezone
from uuid import UUID
from datetime import (
    datetime,
    timezone as dt_timezone,
)  # Import datetime's timezone as dt_timezone
from django.db.models import Q
# New: symbol info helper for inference
from trades.helpers import fetch_symbol_info_for_platform

# Platform-agnostic trading service
from connectors.trading_service import TradingService
# Add alias import so _get_connector can call get_platform_connector and tests can patch it
from utils.concurrency import RedisLock, is_in_cooldown, mark_cooldown

logger = logging.getLogger(__name__)

# -----------------------------------------------
# Close-reason helpers (mapping + inference)
# -----------------------------------------------

def _map_broker_deal_reason_to_close(reason_code: int):
    """Map platform-specific deal reason codes to app close_reason/subreason.
    MT5 ENUM_DEAL_REASON typical values: 0=CLIENT,1=EXPERT,2=MOBILE,3=WEB,4=SL,5=TP,6=SO(StopOut).
    """
    try:
        rc = int(reason_code) if reason_code is not None else None
    except Exception:
        rc = None
    if rc == 4:
        return ("SL_HIT", None)
    if rc == 5:
        return ("TP_HIT", None)
    if rc == 6:
        return ("STOP_OUT", None)
    return (None, None)


def _infer_close_reason(trade: Trade, close_price: Decimal) -> str | None:
    """Infer TP_HIT or SL_HIT by comparing close_price to configured TP/SL within a small tolerance."""
    if close_price is None:
        return None
    try:
        sym = fetch_symbol_info_for_platform(trade.account, trade.instrument)
        pip = Decimal(str(sym.get("pip_size", 0)))
        if pip <= 0:
            return None
    except Exception:
        return None
    tol = pip * Decimal("2")  # 2 pips tolerance
    try:
        tp = Decimal(str(trade.profit_target)) if trade.profit_target is not None else None
        sl = Decimal(str(trade.stop_loss)) if trade.stop_loss is not None else None
    except Exception:
        tp = trade.profit_target
        sl = trade.stop_loss
    if tp is not None and abs(close_price - tp) <= tol:
        return "TP_HIT"
    if sl is not None and abs(close_price - sl) <= tol:
        return "SL_HIT"
    return None


def get_pending_orders(account: Account) -> list:
    """Fetch pending orders using the platform-agnostic TradingService (connector-backed)."""
    try:
        ts = TradingService(account)
        return ts.get_pending_orders_sync() or []
    except Exception as e:
        logger.exception(f"TS_ONLY_PENDING_ORDERS_PATH: failed to fetch pending orders: {e}")
        return []


def get_cached(symbol, tf, ind):
    row = (
        IndicatorData.objects.filter(symbol=symbol, timeframe=tf, indicator_type=ind)
        .order_by("-updated_at")
        .first()
    )
    return row.value if row else None


# snapshot what you want


# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
#                          PARTIAL TRADE CLOSURE
# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
def partially_close_trade(user, trade_id: UUID, volume_to_close: Decimal) -> dict:
    """
    Partially closes an open trade using the platform-agnostic TradingService and updates the database.
    Policy: callers do not branch by platform; all platform differences live behind connectors.
    """
    trade = get_object_or_404(Trade, id=trade_id)

    if trade.account.user != user:
        raise PermissionDenied("Unauthorized to partially close this trade.")

    if trade.trade_status != "open":
        raise ValidationError("Trade is not open, cannot partially close.")

    if not (Decimal("0.01") <= volume_to_close < trade.remaining_size):
        raise ValidationError(
            f"Volume to close ({volume_to_close}) must be between 0.01 and less than remaining size ({trade.remaining_size})."
        )

    account = trade.account

    # Platform-agnostic path via TradingService
    pos_id = str(trade.position_id or trade.order_id or "")
    if not pos_id:
        raise TradeValidationError(
            f"Cannot partially close trade {trade.id}: Missing position ticket (position_id or order_id)."
        )
    try:
        ts = TradingService(account)
        ts.close_position_sync(position_id=pos_id, volume=float(volume_to_close), symbol=trade.instrument)
        logger.info(f"TS_ONLY_PARTIAL_CLOSE_PATH: requested close volume={volume_to_close} for pos_id={pos_id} {trade.instrument}")
        # Immediately sync deals to persist the partial close Order and update remaining_size
        try:
            synchronize_trade_with_platform(trade.id)
        except Exception as sync_e:
            logger.warning(f"TS_ONLY_PARTIAL_CLOSE_PATH: sync after partial close failed: {sync_e}")

        # Best-effort: reload and tag recent close order if any
        trade.refresh_from_db()
        closed_portion_order = (
            Order.objects.filter(trade=trade, status=Order.Status.FILLED)
            .order_by("-filled_at", "-created_at")
            .first()
        )
        if closed_portion_order and not closed_portion_order.close_reason:
            closed_portion_order.close_reason = "STRATEGY_EXIT"
            closed_portion_order.close_subreason = (
                "EXIT_LONG" if (trade.direction or "").upper() == "BUY" else "EXIT_SHORT"
            )
            closed_portion_order.save(update_fields=["close_reason", "close_subreason"])
        trade.refresh_from_db()
    except Exception as e:
        logger.exception(f"TS_ONLY_PARTIAL_CLOSE_PATH: partial close failed: {e}")
        raise BrokerAPIError(str(e))

    profit_on_closed_portion = Decimal("0.00")
    if closed_portion_order and closed_portion_order.volume == volume_to_close:
        for v in [closed_portion_order.profit, closed_portion_order.commission, closed_portion_order.swap]:
            if v is not None:
                try:
                    profit_on_closed_portion += Decimal(str(v))
                except Exception:
                    pass

    return {
        "message": "Trade partially closed successfully.",
        "trade_id": str(trade.id),
        "closed_volume": float(volume_to_close),
        "remaining_volume": float(trade.remaining_size),
        "profit_on_closed_portion": float(profit_on_closed_portion),
        "current_trade_actual_profit_loss": float(trade.actual_profit_loss or 0),
    }


class TradeService:
    def __init__(self, user, validated_data):
        self.user = user
        self.data = validated_data
        # Normalize optional metadata
        self.data.setdefault("live_run_id", None)
        self.data.setdefault("bot_version_id", None)
        self.data.setdefault("correlation_id", None)

    def _get_account(self) -> Account:
        acct = get_object_or_404(Account, id=self.data["account_id"])
        if acct.user_id != self.user.id:
            raise PermissionError("Unauthorized")
        return acct

    def validate(self):
        """
        1. Load the Account instance
        2. Run your risk module (same signature as the old view)
        3. Return (account, final_lot, sl_price, tp_price)
        """
        account = self._get_account()

        limit_price = self.data.get("limit_price")
        rv = validate_trade_request(
            account_id=str(account.id),
            user=self.user,
            symbol=self.data["symbol"],
            trade_direction=self.data["direction"],
            stop_loss_distance=self.data["stop_loss_distance"],
            take_profit_price=float(self.data["take_profit"]),
            risk_percent=float(self.data["risk_percent"]),
            limit_price=float(limit_price) if limit_price is not None else None,
        )
        if "error" in rv:
            raise ValidationError(rv["error"])

        final_lot = rv["lot_size"]
        sl_price = rv["stop_loss_price"]
        tp_price = rv["take_profit_price"]

        # extra guard rails, just like the old view did
        rm = fetch_risk_settings(account.id)
        # Pass account instance as the first argument to perform_risk_checks
        rc = perform_risk_checks(
            account,  # Account instance
            rm,  # Risk settings object or dict
            Decimal(str(final_lot)),  # Ensure final_lot is Decimal (was float)
            self.data["symbol"],
            Decimal(
                str(self.data["risk_percent"])
            ),  # Ensure risk_percent is Decimal (was float)
        )
        if "error" in rc:
            raise ValidationError(rc["error"])

        return account, final_lot, sl_price, tp_price

    # Legacy connector resolution removed; TradingService now mediates MT5 operations.

    def execute_on_broker(
        self, account: Account, final_lot, sl_price, tp_price
    ) -> dict:
        """
    Place the order via TradingService and, when available, attach position details.
        """
        # Phase 1: Idempotency pre-check to avoid duplicate broker submits on bursts
        try:
            live_run_id = self.data.get("live_run_id")
            corr_id = self.data.get("correlation_id")
            symbol = self.data.get("symbol")
            side = self.data.get("direction")
            # Phase 2/3: Names for lock/cooldown keys
            lock_key = (
                f"lock:open:{live_run_id}:{symbol}:{side}" if live_run_id and symbol and side else None
            )
            cooldown_key = (
                f"cooldown:open:{live_run_id}:{symbol}:{side}" if live_run_id and symbol and side else None
            )

            if live_run_id and corr_id:
                existing = (
                    Trade.objects.filter(
                        live_run_id=live_run_id,
                        correlation_id=corr_id,
                        trade_status="open",
                    )
                    .order_by("-created_at")
                    .first()
                )
                if existing:
                    logger.info(
                        f"Idempotency hit: existing open trade found for (live_run={live_run_id}, correlation_id={corr_id}). Skipping broker call."
                    )
                    return {
                        "idempotent": True,
                        "status": "filled",
                        "order_id": existing.order_id,
                        "position_info": {},
                    }
        except Exception as _idem_e:
            logger.warning(f"Idempotency pre-check failed, proceeding with broker call: {_idem_e}")

        # Phase 2: Per-run/symbol/side lock with safe no-op fallback when Redis is unavailable
        if lock_key:
            with RedisLock(lock_key, ttl_ms=getattr(settings, "EXEC_LOCK_TTL_MS", 5000)) as lk:
                if not lk.acquired:
                    logger.info(f"Execution lock miss for {lock_key}; skipping broker submit.")
                    return {"error": "LOCK_NOT_ACQUIRED", "status": "skipped"}
                # Phase 3: Cooldown window check
                if cooldown_key and is_in_cooldown(cooldown_key):
                    logger.info(f"Cooldown active for {cooldown_key}; skipping broker submit.")
                    return {"error": "COOLDOWN_ACTIVE", "status": "skipped"}
                # Proceed under lock via TradingService
                resp = self._submit_with_trading_service(account, final_lot, sl_price, tp_price)
                # If success/filled, mark cooldown
                try:
                    if cooldown_key and resp and resp.get("status") in {"filled", "pending"}:
                        cd = int(getattr(settings, "MIN_ENTRY_COOLDOWN_SEC", 0) or 0)
                        if cd > 0:
                            mark_cooldown(cooldown_key, cd)
                except Exception as _cd_e:
                    logger.warning(f"Failed to mark cooldown for {cooldown_key}: {_cd_e}")
                return resp
        # No lock key context -> direct TS submit
        return self._submit_with_trading_service(account, final_lot, sl_price, tp_price)

    def _submit_with_trading_service(self, account: Account, final_lot, sl_price, tp_price) -> dict:
        """TS-only order placement; TradingService handles platform specifics."""
        try:
            ts = TradingService(account)
            limit_price_float = (
                float(self.data["limit_price"]) if self.data.get("limit_price") is not None else None
            )
            resp = ts.place_trade_sync(
                symbol=self.data["symbol"],
                lot_size=final_lot,
                direction=self.data["direction"],
                stop_loss=sl_price,
                take_profit=tp_price,
                order_type=self.data.get("order_type", "MARKET"),
                limit_price=limit_price_float,
                sl_distance=float(self.data.get("stop_loss_distance")) if self.data.get("stop_loss_distance") is not None else None,
                tp_distance=float(self.data.get("tp_distance")) if self.data.get("tp_distance") is not None else None,
            )
            logger.info(f"TS_ONLY_EXEC_PATH: trade placed via TradingService resp={resp}")

            if resp.get("status") == "filled":
                opened_pos_ticket = resp.get("opened_position_ticket") or resp.get("order_id")
                if opened_pos_ticket:
                    try:
                        p = ts.get_position_details_sync(str(opened_pos_ticket))
                        # Map PositionInfo to legacy dict shape expected downstream
                        pos_details = {
                            "ticket": p.position_id,
                            "symbol": p.symbol,
                            "type": 0 if (getattr(p, "direction", "").upper() == "BUY") else 1,
                            "volume": p.volume,
                            "price_open": p.open_price,
                            "price_current": p.current_price,
                            "sl": p.stop_loss,
                            "tp": p.take_profit,
                            "profit": p.profit,
                            "swap": p.swap,
                            "commission": p.commission,
                        }
                        logger.info(
                            f"TS_ONLY_EXEC_PATH: attached position_info ticket={pos_details.get('ticket')} symbol={pos_details.get('symbol')}"
                        )
                    except Exception as e:
                        logger.warning(f"TS_ONLY_EXEC_PATH: get_position_details failed: {e}")
                        pos_details = {}
                    resp["position_info"] = pos_details
                else:
                    resp["position_info"] = {}
            return resp
        except Exception as e:
            logger.exception(f"TS_ONLY_EXEC_PATH: TradingService execution failed: {e}")
            return {"error": str(e), "status": "failed"}

    def persist(self, account: Account, resp: dict, final_lot, sl_price, tp_price):
        """
        Save the Order and, if filled, the Trade and any ProfitTarget legs.
        """
        # Fail-fast on broker error or missing order id
        if not resp or resp.get("status") == "failed" or "order_id" not in resp:
            err = (resp or {}).get("error") if isinstance(resp, dict) else None
            logger.error(f"Broker execution failed or returned invalid payload: {resp}")
            raise APIException(f"Broker execution failed: {err or 'unknown error'}")

        # Phase 1: If broker step was skipped due to idempotency, return existing records
        if resp.get("idempotent"):
            try:
                live_run_id = self.data.get("live_run_id")
                corr_id = self.data.get("correlation_id")
                existing_trade = (
                    Trade.objects.filter(
                        live_run_id=live_run_id,
                        correlation_id=corr_id,
                    )
                    .order_by("-created_at")
                    .first()
                )
                if existing_trade:
                    existing_order = (
                        Order.objects.filter(trade=existing_trade)
                        .order_by("-created_at")
                        .first()
                    )
                    if existing_order:
                        logger.info(
                            f"Idempotent persist: returning existing order/trade (order={existing_order.broker_order_id}, trade={existing_trade.id})."
                        )
                        return existing_order, existing_trade
                    else:
                        # Fallback: attempt direct lookup by broker_order_id
                        by_broker = (
                            Order.objects.filter(broker_order_id=existing_trade.order_id)
                            .order_by("-created_at")
                            .first()
                        )
                        if by_broker:
                            return by_broker, existing_trade
                        logger.warning(
                            f"Idempotent persist: existing trade found but no order linked. Proceeding to create a new Order shell to maintain response shape."
                        )
                        # Create a minimal shadow order to preserve invariants
                        shadow = Order.objects.create(
                            account=account,
                            instrument=existing_trade.instrument,
                            direction=existing_trade.direction,
                            order_type=self.data.get("order_type", "MARKET"),
                            volume=Decimal(final_lot),
                            price=(Decimal(self.data["limit_price"]) if self.data.get("limit_price") is not None else None),
                            stop_loss=Decimal(sl_price),
                            take_profit=Decimal(tp_price),
                            time_in_force=self.data.get("time_in_force", "GTC"),
                            broker_order_id=existing_trade.order_id,
                            status=Order.Status.FILLED,
                            risk_percent=Decimal(self.data["risk_percent"]),
                            projected_profit=Decimal(self.data.get("projected_profit", 0) or 0),
                            projected_loss=Decimal(self.data.get("projected_loss", 0) or 0),
                            rr_ratio=Decimal(self.data.get("rr_ratio", 0) or 0),
                            trade=existing_trade,
                        )
                        return shadow, existing_trade
            except Exception as _idem_persist_e:
                logger.error(f"Idempotent persist handling failed, falling back to normal persist: {_idem_persist_e}")
                # continue to normal flow

        # Gracefully handle skip/error from execution gate (lock/cooldown)
        if resp.get("status") == "skipped" or resp.get("error") in {"LOCK_NOT_ACQUIRED", "COOLDOWN_ACTIVE"}:
            logger.info(f"Persist skipped due to execution gate: {resp}")
            return None, None

        snapshot = {
            "RSI_M1": get_cached(self.data["symbol"], "M1", "RSI"),
            "ATR_M1": get_cached(self.data["symbol"], "M1", "ATR"),
        }
        # 1️⃣ Order row
        order = Order.objects.create(
            id=uuid4(),
            account=account,
            instrument=self.data["symbol"],
            direction=self.data["direction"],
            order_type=self.data["order_type"],
            volume=Decimal(final_lot),
            price=(
                Decimal(self.data["limit_price"]) if self.data.get("limit_price") is not None else None
            ),
            stop_loss=Decimal(sl_price),
            take_profit=Decimal(tp_price),
            time_in_force=self.data.get("time_in_force", "GTC"),
            broker_order_id=resp["order_id"],
            status=resp.get("status", "pending"),
            risk_percent=Decimal(self.data["risk_percent"]),
            projected_profit=Decimal(self.data.get("projected_profit", 0) or 0),
            projected_loss=Decimal(self.data.get("projected_loss", 0) or 0),
            rr_ratio=Decimal(self.data.get("rr_ratio", 0) or 0),
        )

        trade = None
        # Create a Trade if the order is filled OR a live position ticket is present (cTrader may accept then attach position immediately)
        if resp.get("status") == "filled" or resp.get("opened_position_ticket"):
            raw_position_info = resp.get("position_info", {})

            # Prepare data for Trade object creation, using fallbacks if necessary
            trade_lot_size = final_lot
            trade_entry_price = resp.get("price")  # Default to price from place_trade (tick.ask/bid)
            trade_sl = sl_price
            trade_tp = tp_price

            # Fetch contract_size once for conversions
            cs: Decimal | None = None
            try:
                sym_info = fetch_symbol_info_for_platform(account, self.data["symbol"]) or {}
                contract_size = sym_info.get("contract_size") or sym_info.get("contractSize")
                if contract_size is not None:
                    cs = Decimal(str(contract_size))
            except Exception:
                cs = None

            # If response carries server_response with tradeData.volume in units, convert to lots as a baseline
            try:
                sr = resp.get("server_response") or {}
                order_info = sr.get("order") or {}
                td = order_info.get("tradeData") or {}
                raw_vol = td.get("volume")
                if cs and raw_vol is not None:
                    vol_dec = Decimal(str(raw_vol))
                    if cs > 0 and vol_dec >= cs:
                        trade_lot_size = float(vol_dec / cs)
            except Exception:
                pass

            # If we have a position ticket but no attached position_info, best-effort fetch from platform
            if (not raw_position_info) and resp.get("opened_position_ticket"):
                try:
                    ts = TradingService(account)
                    p = ts.get_position_details_sync(str(resp.get("opened_position_ticket")))
                    # Map PositionInfo to dict-like shape used below for overrides
                    raw_position_info = {
                        "ticket": p.position_id,
                        "position_id": p.position_id,
                        "symbol": p.symbol,
                        "type": 0 if (getattr(p, "direction", "").upper() == "BUY") else 1,
                        "volume": p.volume,
                        "price_open": p.open_price,
                        "price_current": p.current_price,
                        "sl": p.stop_loss,
                        "tp": p.take_profit,
                        "profit": p.profit,
                        "swap": p.swap,
                        "commission": p.commission,
                    }
                except Exception as e:
                    logger.warning(f"TS_ONLY_EXEC_PATH: get_position_details (pending path) failed: {e}")

            if raw_position_info and not raw_position_info.get("error"):
                trade_lot_size = raw_position_info.get("volume", trade_lot_size)
                # Override entry_price if available from fetched position details
                ro_price_open = raw_position_info.get("price_open")
                if ro_price_open is not None:
                    trade_entry_price = ro_price_open
                # Only override SL/TP if the platform returned non-null values; else keep calculated defaults
                ro_sl = raw_position_info.get("sl")
                if ro_sl is not None:
                    trade_sl = ro_sl
                ro_tp = raw_position_info.get("tp")
                if ro_tp is not None:
                    trade_tp = ro_tp
            elif raw_position_info.get("error"):
                logger.warning(
                    f"--- trades/services.py (persist): position_info has error: {raw_position_info.get('error')}. Using calculated/default values for some trade details."
                )

            # Convert native volume units to lots when needed using contract_size
            try:
                if cs is not None:
                    vol_dec2 = Decimal(str(trade_lot_size))
                    if cs > 0 and vol_dec2 >= cs:
                        lots2 = vol_dec2 / cs
                        logger.info(
                            f"Normalized broker volume to lots: raw={vol_dec2} units, contract_size={cs}, lots={lots2}"
                        )
                        trade_lot_size = float(lots2)
            except Exception as _conv_e:
                logger.debug(f"Volume-to-lots conversion skipped due to error: {_conv_e}")

            # Determine the position_id for the Trade record (connector-agnostic)
            db_trade_position_id = None
            # Prefer explicit position info from TradingService
            if raw_position_info and not raw_position_info.get("error"):
                db_trade_position_id = (
                    raw_position_info.get("ticket") or raw_position_info.get("position_id")
                )
                if db_trade_position_id:
                    logger.info(
                        f"--- trades/services.py (persist): Using position info ticket {db_trade_position_id} as Trade.position_id."
                    )
            # Fallback to any broker-provided position identifier fields
            if not db_trade_position_id:
                db_trade_position_id = (resp.get("opened_position_ticket") or resp.get("position_id"))
            # Last resort: some brokers equate market order id to position id; allow only for MARKET orders
            if not db_trade_position_id and (self.data.get("order_type", "").upper() == "MARKET"):
                db_trade_position_id = resp.get("order_id")

            if db_trade_position_id is None:
                logger.warning(
                    f"Trade.position_id will be NULL for order {resp.get('order_id')}. Fetched position_info: {raw_position_info}"
                )

            trade = Trade.objects.create(
                account=account,
                instrument=self.data["symbol"],
                direction=self.data["direction"],
                lot_size=Decimal(str(trade_lot_size)),
                remaining_size=Decimal(str(trade_lot_size)),
                entry_price=(Decimal(str(trade_entry_price)) if trade_entry_price is not None else None),
                stop_loss=(Decimal(str(trade_sl)) if trade_sl is not None else None),
                profit_target=(Decimal(str(trade_tp)) if trade_tp is not None else None),
                trade_status="open",
                order_id=resp["order_id"],
                deal_id=resp.get("deal_id"),
                position_id=db_trade_position_id,
                risk_percent=Decimal(self.data["risk_percent"]),
                projected_profit=Decimal(self.data.get("projected_profit", 0) or 0),
                projected_loss=Decimal(self.data.get("projected_loss", 0) or 0),
                rr_ratio=Decimal(self.data.get("rr_ratio", 0) or 0),
                reason=self.data.get("reason", ""),
                indicators=snapshot,
                # New lineage fields
                source=self.data.get("source", "MANUAL"),
                live_run_id=self.data.get("live_run_id"),
                bot_version_id=self.data.get("bot_version_id"),
                correlation_id=self.data.get("correlation_id"),
            )
            # Assign ForeignKeys using the _id convention, which is standard.
            if trade and self.data.get("live_run_id"):
                trade.live_run_id = self.data.get("live_run_id")
            if trade and self.data.get("bot_version_id"):
                trade.bot_version_id = self.data.get("bot_version_id")
            if trade:
                trade.save()
            order.trade = trade
            order.save(update_fields=["trade"])

        # 2️⃣ ProfitTarget legs
        if self.data.get("partial_profit") and trade:
            total = Decimal(final_lot)
            for leg in sorted(self.data["targets"], key=lambda x: x["rank"]):
                cfg = {
                    **leg,
                    "stop_loss_price": trade.stop_loss,
                    "symbol": trade.instrument,
                    # add timeframe if you use ATR
                }
                price = derive_target_price(
                    trade.entry_price, cfg, trade.direction  # ← now included
                )
                vol = (total * Decimal(str(leg["share"]))).quantize(Decimal("0.01"))
                ProfitTarget.objects.create(
                    trade=trade,
                    rank=leg["rank"],
                    target_price=price,
                    target_volume=vol,
                )

        return order, trade

    def build_response(self, order: Order, trade: Trade) -> dict:
        """
        Prepare the final JSON shape for the view.
        """
        if not order:
            # Skipped or gated action
            out = {
                "message": "Order skipped by execution gate",
                "order_status": "skipped",
            }
            if trade:
                out.update({"trade_id": str(trade.id)})
            return out
        out = {
            "message": "Order accepted",
            "order_id": order.broker_order_id,
            "order_status": order.status,
        }
        if trade:
            out.update({"trade_id": str(trade.id)})
            # Include entry_price only if available to avoid casting None
            if trade.entry_price is not None:
                try:
                    out["entry_price"] = float(trade.entry_price)
                except Exception:
                    # best-effort: skip if not castable
                    pass
        return out


def close_trade_globally(user, trade_id: UUID, client_close_reason: str | None = None, client_close_subreason: str | None = None) -> dict:
    """
    Closes a trade, performs platform-specific actions, and updates the database.
    If client_close_reason is provided (e.g., MANUAL_CLOSE), prefer it when tagging.
    """
    trade = get_object_or_404(Trade, id=trade_id)

    if trade.account.user != user:
        raise PermissionDenied("Unauthorized to close this trade")

    if trade.trade_status != "open":
        raise ValidationError("Trade is already closed")

    account = trade.account

    # Platform-agnostic via TradingService
    pos_id = str(trade.position_id or trade.order_id or "")
    if not pos_id:
        raise TradeValidationError(
            f"Cannot close trade {trade.id}: Missing position ticket (position_id or order_id)."
        )
    try:
        ts = TradingService(account)
        resp = ts.close_position_sync(position_id=pos_id, volume=float(trade.remaining_size), symbol=trade.instrument)
        logger.info(f"TS_ONLY_CLOSE_PATH: close_position resp={resp}")
        # Global approach: immediately attempt a sync if supported to reflect remaining_size/status
        try:
            synchronize_trade_with_platform(trade.id)
        except Exception as sync_e:
            logger.warning(f"TS_ONLY_CLOSE_PATH: post-close sync failed: {sync_e}")
    except Exception as e:
        logger.exception(f"TS_ONLY_CLOSE_PATH: close_position failed: {e}")
        raise BrokerAPIError(str(e))

    # After successful closure, best-effort refresh before tagging
    try:
        trade.refresh_from_db()
    except Exception:
        pass

    # Refresh instance from DB and tag reasons
    trade.refresh_from_db()

    last_close_order = (
        Order.objects.filter(trade=trade, status=Order.Status.FILLED)
        .order_by("-filled_at", "-created_at")
        .first()
    )

    preferred_reason = (client_close_reason or "").strip().upper() if client_close_reason else None
    preferred_sub = (client_close_subreason or None)

    if last_close_order and (preferred_reason or not last_close_order.close_reason):
        if preferred_reason:
            last_close_order.close_reason = preferred_reason
            last_close_order.close_subreason = preferred_sub
        elif not last_close_order.close_reason:
            last_close_order.close_reason = "STRATEGY_EXIT"
            last_close_order.close_subreason = (
                "EXIT_LONG" if (trade.direction or "").upper() == "BUY" else "EXIT_SHORT"
            )
        last_close_order.save(update_fields=["close_reason", "close_subreason"])

    if trade.trade_status == "closed" and (preferred_reason or not trade.close_reason):
        if preferred_reason:
            trade.close_reason = preferred_reason
            trade.close_subreason = preferred_sub
        else:
            if last_close_order and last_close_order.close_reason:
                trade.close_reason = last_close_order.close_reason
                trade.close_subreason = last_close_order.close_subreason
            else:
                last_price = last_close_order.filled_price if last_close_order else None
                try:
                    last_price_dec = Decimal(str(last_price)) if last_price is not None else None
                except Exception:
                    last_price_dec = None
                inferred = _infer_close_reason(trade, last_price_dec) if last_price_dec is not None else None
                trade.close_reason = inferred or "STRATEGY_EXIT"
                trade.close_subreason = (
                    "EXIT_LONG" if (trade.direction or "").upper() == "BUY" else "EXIT_SHORT"
                )
        trade.save(update_fields=["close_reason", "close_subreason"])

    return {
        "message": "Trade closed successfully",
        "trade_id": str(trade.id),
        "actual_profit_loss": float(
            trade.actual_profit_loss if trade.actual_profit_loss is not None else 0
        ),
    }


def synchronize_trade_with_platform(
    trade_id: UUID,
):
    """
    Synchronizes a single trade record with the trading platform (e.g., MT5).
    Fetches the latest deals, updates order history, remaining size, status, and P/L.
    """
    try:
        trade_instance = get_object_or_404(Trade, id=trade_id)
    except Trade.DoesNotExist:
        raise TradeValidationError(f"Trade with id {trade_id} not found.")

    # Use TradingService sync wrapper to fetch platform sync data when supported
    if not trade_instance.position_id:
        raise TradeValidationError(
            f"Trade {trade_instance.id} does not have a position_id. Cannot sync with platform."
        )
    ts = TradingService(trade_instance.account)
    try:
        sync_data = ts.fetch_trade_sync_data_sync(str(trade_instance.position_id), trade_instance.instrument)
    except Exception as e:
        raise TradeSyncError(f"Failed to retrieve sync data from platform: {e}")

    if not sync_data:
        raise TradeSyncError("Failed to retrieve sync data from platform.")

    if sync_data.get("error_message"):
        raise BrokerAPIError(f"Platform error: {sync_data.get('error_message')}")

    # 1. Update/Create Order records from sync_data["deals"] with closure tagging
    created_deals = 0
    existing_broker_deal_ids = set(
        trade_instance.order_history.values_list("broker_deal_id", flat=True).exclude(
            broker_deal_id__isnull=True
        )
    )

    for deal_info in sync_data.get("deals", []):
        broker_deal_id = deal_info.get("ticket")
        if broker_deal_id and broker_deal_id not in existing_broker_deal_ids:
            close_reason, close_subreason = _map_broker_deal_reason_to_close(deal_info.get("reason"))
            created_order = Order.objects.create(
                account=trade_instance.account,
                instrument=deal_info.get("symbol"),
                direction=(Order.Direction.BUY if deal_info.get("type") == 0 else Order.Direction.SELL),
                order_type=Order.OrderType.MARKET,
                volume=deal_info.get("volume"),
                price=deal_info.get("price"),
                status=Order.Status.FILLED,
                broker_order_id=deal_info.get("order"),
                broker_deal_id=broker_deal_id,
                filled_price=deal_info.get("price"),
                filled_volume=deal_info.get("volume"),
                filled_at=(datetime.fromtimestamp(deal_info.get("time"), tz=dt_timezone.utc) if deal_info.get("time") else None),
                profit=deal_info.get("profit"),
                commission=deal_info.get("commission"),
                swap=deal_info.get("swap"),
                broker_deal_reason_code=deal_info.get("reason"),
                trade=trade_instance,
                close_reason=close_reason,
                close_subreason=close_subreason,
            )
            existing_broker_deal_ids.add(broker_deal_id)
            created_deals += 1

    # 2. Update Trade.remaining_size
    trade_instance.remaining_size = sync_data.get("platform_remaining_size", trade_instance.remaining_size)

    # 3. Update Trade status if closed and set close_reason
    if sync_data.get("is_closed_on_platform") and trade_instance.trade_status == "open":
        trade_instance.trade_status = "closed"
        trade_instance.close_price = sync_data.get("last_deal_price")

        latest_deal_ts = sync_data.get("latest_deal_timestamp")
        if latest_deal_ts:
            trade_instance.closed_at = datetime.fromtimestamp(latest_deal_ts, tz=dt_timezone.utc)
        else:
            trade_instance.closed_at = django_timezone.now()

        # Normalize to Decimal to avoid float + Decimal TypeError
        final_profit_raw = sync_data.get("final_profit")
        final_commission_raw = sync_data.get("final_commission")
        final_swap_raw = sync_data.get("final_swap")
        try:
            final_profit = Decimal(str(final_profit_raw)) if final_profit_raw is not None else Decimal("0")
        except Exception:
            final_profit = Decimal("0")
        try:
            final_commission = Decimal(str(final_commission_raw)) if final_commission_raw is not None else Decimal("0")
        except Exception:
            final_commission = Decimal("0")
        try:
            final_swap = Decimal(str(final_swap_raw)) if final_swap_raw is not None else Decimal("0")
        except Exception:
            final_swap = Decimal("0")

        trade_instance.actual_profit_loss = final_profit + final_commission + final_swap

        # Set trade close_reason from the last filled order, else infer
        if not trade_instance.close_reason:
            last_close_order = (
                trade_instance.order_history.filter(status=Order.Status.FILLED)
                .order_by("-filled_at", "-created_at")
                .first()
            )
            if last_close_order and last_close_order.close_reason:
                trade_instance.close_reason = last_close_order.close_reason
                trade_instance.close_subreason = last_close_order.close_subreason
            else:
                last_price = last_close_order.filled_price if last_close_order else None
                try:
                    last_price_dec = Decimal(str(last_price)) if last_price is not None else None
                except Exception:
                    last_price_dec = None
                inferred = _infer_close_reason(trade_instance, last_price_dec) if last_price_dec is not None else None
                trade_instance.close_reason = inferred or trade_instance.close_reason
                if not trade_instance.close_subreason:
                    trade_instance.close_subreason = (
                        "EXIT_LONG" if (trade_instance.direction or "").upper() == "BUY" else "EXIT_SHORT"
                    )
    # Persist any changes to the Trade instance
    try:
        trade_instance.save()
    except Exception as _save_e:
        logger.warning(f"SYNC_SAVE_WARN: failed to save trade {trade_instance.id}: {_save_e}")

    # Normalize and return a consistent result dict for Celery tasks
    try:
        remaining = float(trade_instance.remaining_size) if trade_instance.remaining_size is not None else None
    except Exception:
        remaining = None

    return {
        "trade_id": str(trade_instance.id),
        "created_deal_orders": created_deals,
        "is_closed_on_platform": bool(sync_data.get("is_closed_on_platform")),
        "remaining_size": remaining,
        "final_profit": float(sync_data.get("final_profit") or 0) if sync_data.get("is_closed_on_platform") else None,
        "status": "ok",
    }


# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
#                  UPDATE TRADE STOP LOSS / TAKE PROFIT
# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++


def update_trade_protection_levels(
    user, trade_id: UUID, new_stop_loss: Decimal = None, new_take_profit: Decimal = None
) -> dict:
    """
    Updates the take profit for an open trade using TradingService. SL updates moved to dedicated function.
    """
    trade = get_object_or_404(Trade, id=trade_id)

    if trade.account.user != user:
        raise PermissionDenied("Unauthorized to update this trade's protection levels.")

    if trade.trade_status != "open":
        raise ValidationError("Protection levels can only be updated for open trades.")

    if new_take_profit is None:
        raise ValidationError("new_take_profit must be provided.")

    if new_stop_loss is not None:
        raise ValidationError("This endpoint is only for updating take profit. Use the SL update endpoint.")

    account = trade.account

    if (account.platform or "").upper() == "MT5":
        pos_id = str(trade.position_id or trade.order_id or "")
        if not pos_id:
            raise TradeValidationError(
                f"Cannot update TP for trade {trade.id}: Missing position ticket (position_id or order_id)."
            )
        try:
            ts = TradingService(account)
            # Preserve SL, set new TP
            sl = float(trade.stop_loss) if trade.stop_loss is not None else None
            resp = ts.modify_position_protection_sync(
                position_id=pos_id,
                symbol=trade.instrument,
                stop_loss=sl,
                take_profit=float(new_take_profit),
            )
            logger.info(f"TS_ONLY_PROTECTION_PATH: modify TP resp={resp}")
        except Exception as e:
            logger.exception(f"TS_ONLY_PROTECTION_PATH: modify TP failed: {e}")
            raise BrokerAPIError(str(e))
    elif (account.platform or "").lower() in ("ctrader", "ctrader") or account.platform == "cTrader":
        # Use TradingService + cTrader HTTP connector to amend protection
        pos_id = str(trade.position_id or trade.order_id or "")
        if not pos_id:
            raise TradeValidationError(
                f"Cannot update TP for trade {trade.id}: Missing position ticket (position_id or order_id)."
            )
        try:
            ts = TradingService(account)
            sl = float(trade.stop_loss) if trade.stop_loss is not None else None
            resp = ts.modify_position_protection_sync(
                position_id=pos_id,
                symbol=trade.instrument,
                stop_loss=sl,
                take_profit=float(new_take_profit),
            )
            logger.info(f"CTRADER_PROTECTION_PATH: modify TP resp={resp}")
        except Exception as e:
            logger.exception(f"CTRADER_PROTECTION_PATH: modify TP failed: {e}")
            raise BrokerAPIError(str(e))
    else:
        raise APIException(f"Unsupported trading platform: {account.platform}")

    # Update DB
    trade.profit_target = Decimal(str(new_take_profit))
    trade.save(update_fields=["profit_target"])

    return {
        "message": "Trade take profit updated successfully.",
        "trade_id": str(trade.id),
        "new_take_profit": float(trade.profit_target),
        "platform_response": resp,
    }


def update_trade_stop_loss_globally(
    user,
    trade_id: UUID,
    sl_update_type: str,  # "breakeven", "distance_pips", "distance_price", "specific_price"
    value: Decimal = None,
    specific_price: Decimal = None,
) -> dict:
    """
    Updates the stop loss for an open trade based on the specified update type via TradingService.
    """
    trade = get_object_or_404(Trade, id=trade_id)

    if trade.account.user != user:
        raise PermissionDenied("Unauthorized to update this trade's stop loss.")

    if trade.trade_status != "open":
        raise ValidationError("Stop loss can only be updated for open trades.")

    account = trade.account

    # Compute new SL
    symbol_info = fetch_symbol_info_for_platform(account, trade.instrument) or {}
    pip = Decimal(str(symbol_info.get("pip_size", 0) or 0))

    def to_decimal(x):
        return Decimal(str(x)) if x is not None else None

    current_entry = to_decimal(trade.entry_price)
    current_tp = to_decimal(trade.profit_target)

    if sl_update_type == "breakeven":
        if current_entry is None:
            raise ValidationError("Cannot compute breakeven without entry price.")
        new_sl_price = current_entry
    elif sl_update_type == "distance_pips":
        if value is None or pip <= 0:
            raise ValidationError("distance_pips requires value and valid pip_size.")
        if (trade.direction or "").upper() == "BUY":
            new_sl_price = current_entry - (to_decimal(value) * pip)
        else:
            new_sl_price = current_entry + (to_decimal(value) * pip)
    elif sl_update_type == "distance_price":
        if value is None:
            raise ValidationError("distance_price requires value.")
        if (trade.direction or "").upper() == "BUY":
            new_sl_price = current_entry - to_decimal(value)
        else:
            new_sl_price = current_entry + to_decimal(value)
    elif sl_update_type == "specific_price":
        if specific_price is None:
            raise ValidationError("specific_price requires specific_price.")
        new_sl_price = to_decimal(specific_price)
    else:
        raise ValidationError(f"Unsupported sl_update_type: {sl_update_type}")

    # Bounds: don't cross TP if exists
    if current_tp is not None and new_sl_price is not None:
        if (trade.direction or "").upper() == "BUY" and new_sl_price > current_tp:
            new_sl_price = current_tp
        if (trade.direction or "").upper() == "SELL" and new_sl_price < current_tp:
            new_sl_price = current_tp

    pos_id = str(trade.position_id or trade.order_id or "")
    if not pos_id:
        raise TradeValidationError(
            f"Cannot update SL for trade {trade.id}: Missing position ticket (position_id or order_id)."
        )

    if (account.platform or "").upper() == "MT5":
        try:
            ts = TradingService(account)
            tp = float(trade.profit_target) if trade.profit_target is not None else None
            resp = ts.modify_position_protection_sync(
                position_id=pos_id,
                symbol=trade.instrument,
                stop_loss=float(new_sl_price) if new_sl_price is not None else None,
                take_profit=tp,
            )
            logger.info(f"TS_ONLY_PROTECTION_PATH: modify SL resp={resp}")
        except Exception as e:
            logger.exception(f"TS_ONLY_PROTECTION_PATH: modify SL failed: {e}")
            raise BrokerAPIError(str(e))
    elif (account.platform or "").lower() in ("ctrader", "ctrader") or account.platform == "cTrader":
        try:
            ts = TradingService(account)
            tp = float(trade.profit_target) if trade.profit_target is not None else None
            resp = ts.modify_position_protection_sync(
                position_id=pos_id,
                symbol=trade.instrument,
                stop_loss=float(new_sl_price) if new_sl_price is not None else None,
                take_profit=tp,
            )
            logger.info(f"CTRADER_PROTECTION_PATH: modify SL resp={resp}")
        except Exception as e:
            logger.exception(f"CTRADER_PROTECTION_PATH: modify SL failed: {e}")
            raise BrokerAPIError(str(e))
    else:
        raise APIException(f"Unsupported trading platform: {account.platform}")

    trade.stop_loss = Decimal(str(new_sl_price)) if new_sl_price is not None else None
    trade.save(update_fields=["stop_loss"])

    return {
        "message": "Trade stop loss updated successfully.",
        "trade_id": str(trade.id),
        "new_stop_loss": float(trade.stop_loss) if trade.stop_loss is not None else None,
        "platform_response": resp,
    }


def cancel_pending_order(user, order_id: str) -> dict:
    """
    Cancels a pending order on the platform and updates its status in the database.
    """
    broker_order_id = None
    order_id_uuid = None
    order = None
    try:
        order_id_uuid = UUID(order_id, version=4)  # Try to parse as UUID
    except Exception:
        pass
    try:
        broker_order_id = int(order_id)  # Try to parse as integer
    except Exception:
        pass
    if broker_order_id:
        order = Order.objects.filter(
            broker_order_id=broker_order_id, account__user=user
        ).first()
    elif order_id_uuid:
        order = Order.objects.filter(id=order_id_uuid, account__user=user).first()

    if not order:
        raise ValidationError(f"Order with id {order_id} not found.")

    if order.account.user != user:
        raise PermissionDenied("Unauthorized to cancel this order.")

    if order.status != Order.Status.PENDING.value:
        raise ValidationError(f"Order is not pending, its status is '{order.status}'.")

    # Platform-agnostic cancel via TradingService
    if not order.broker_order_id:
        raise TradeValidationError(
            f"Cannot cancel order {order.id}: Missing broker_order_id."
        )

    try:
        ts = TradingService(order.account)
        cancel_result = ts.cancel_order_sync(str(order.broker_order_id))
    except Exception as e:
        logger.exception(f"TS_ONLY_CANCEL_PATH: cancel order failed: {e}")
        raise BrokerAPIError(str(e))

    # Update order status in the database
    order.status = Order.Status.CANCELLED
    order.save(update_fields=["status"])

    return {
        "message": "Order canceled successfully.",
        "order_id": str(order.id),
        "platform_response": cancel_result,
    }
