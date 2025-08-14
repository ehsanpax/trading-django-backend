# trades/services.py
import logging
from django.conf import settings
from decimal import Decimal
from django.shortcuts import get_object_or_404
from accounts.models import Account, MT5Account, CTraderAccount
from connectors.ctrader_client import CTraderClient
from trading_platform.mt5_api_client import MT5APIClient
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

# Phase 0 addition: use minimal connector factory for TradeService
from connectors.factory import get_connector as get_platform_connector
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
    """
    Fetches pending orders for a given account from the appropriate platform.
    """
    if account.platform == "MT5":
        try:
            mt5_account = account.mt5_account
        except MT5Account.DoesNotExist:
            raise TradeValidationError("No linked MT5 account found for this account.")

        client = MT5APIClient(
            base_url=settings.MT5_API_BASE_URL,
            account_id=mt5_account.account_number,
            password=mt5_account.encrypted_password,
            broker_server=mt5_account.broker_server,
            internal_account_id=str(account.id),
        )

        response = client.get_all_open_positions_rest()
        all_trades = response.get("open_positions", [])
        pending_orders = [
            trade for trade in all_trades if trade.get("type") == "pending_order"
        ]
        return pending_orders

    elif account.platform == "cTrader":
        # Placeholder for cTrader implementation
        return []
    else:
        raise NotImplementedError(
            f"Pending order retrieval is not implemented for platform: {account.platform}"
        )


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
    Partially closes an open trade, performs platform-specific actions,
    and updates the database. Tags the closing Order with STRATEGY_EXIT by default
    unless broker mapping sets a more specific reason.
    """
    trade = get_object_or_404(Trade, id=trade_id)

    if trade.account.user != user:
        raise PermissionDenied("Unauthorized to partially close this trade.")

    if trade.trade_status != "open":
        raise ValidationError("Trade is not open, cannot partially close.")

    if not (Decimal("0.01") <= volume_to_close < trade.remaining_size):
        raise ValidationError(
            f"Volume to close ({volume_to_close}) must be between 0.01 and "
            f"less than remaining size ({trade.remaining_size}). "
            f"For full closure, use the close trade endpoint."
        )

    connector = None  # Initialize connector

    if trade.account.platform == "MT5":
        try:
            mt5_account = trade.account.mt5_account
        except MT5Account.DoesNotExist:
            raise TradeValidationError(
                "No linked MT5 account found for this trade's account."
            )

        client = MT5APIClient(
            base_url=settings.MT5_API_BASE_URL,
            account_id=mt5_account.account_number,
            password=mt5_account.encrypted_password,
            broker_server=mt5_account.broker_server,
            internal_account_id=str(trade.account.id),
        )

        if not trade.position_id:
            raise TradeValidationError(
                f"Cannot partially close trade {trade.id}: Missing MT5 position ticket (position_id)."
            )

        client.close_trade(
            ticket=trade.position_id,
            volume=float(volume_to_close),
            symbol=trade.instrument,
        )

        # Successfully issued partial close command to broker
        # Now, synchronize to get the deal and update trade state
        try:
            synchronize_trade_with_platform(
                trade_id=trade.id, existing_connector=connector
            )
        except (BrokerAPIError, BrokerConnectionError, TradeSyncError) as e:
            # This is problematic: broker action succeeded, but DB sync failed.
            # Log this error thoroughly. The trade state in DB might be stale.
            # For now, we'll raise an exception, but a more robust solution might involve
            # retrying sync or flagging the trade for manual review.
            logger.critical(
                f"Trade {trade.id} partially closed on MT5, but DB sync failed: {e}"
            )
            raise TradeSyncError(
                f"Partially closed on platform, but DB sync failed: {e}. Please check trade status."
            )

        # Find the latest order related to this trade to tag P/L of the closed portion
        # This assumes synchronize_trade_with_platform created an Order for the partial close deal.
        # We sort by filled_at or created_at to get the most recent one.
        closed_portion_order = (
            Order.objects.filter(trade=trade, status=Order.Status.FILLED)
            .order_by("-filled_at", "-created_at")
            .first()
        )

        # Default tagging for strategy-driven partial close
        if closed_portion_order and not closed_portion_order.close_reason:
            closed_portion_order.close_reason = "STRATEGY_EXIT"
            closed_portion_order.close_subreason = (
                "EXIT_LONG" if (trade.direction or "").upper() == "BUY" else "EXIT_SHORT"
            )
            closed_portion_order.save(update_fields=["close_reason", "close_subreason"])

        # Refresh trade instance from DB after sync
        trade.refresh_from_db()

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

    elif trade.account.platform == "cTrader":
        raise APIException("cTrader partial close not implemented yet.")
    else:
        raise APIException(f"Unsupported trading platform: {trade.account.platform}")


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

    def _get_connector(self, account: Account):
        """Phase 0: delegate connector resolution to factory to prepare for multi-platform support."""
        return get_platform_connector(account)

    def execute_on_broker(
        self, account: Account, final_lot, sl_price, tp_price
    ) -> dict:
        """
        Actually place the order on MT5 or cTrader, then for MT5-filled trades
        immediately fetch the live position details.
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
                # Proceed under lock
                resp = self._execute_broker_call(account, final_lot, sl_price, tp_price)
                # If success/filled, mark cooldown
                try:
                    if cooldown_key and resp and resp.get("status") in {"filled", "pending"}:
                        cd = int(getattr(settings, "MIN_ENTRY_COOLDOWN_SEC", 0) or 0)
                        if cd > 0:
                            mark_cooldown(cooldown_key, cd)
                except Exception as _cd_e:
                    logger.warning(f"Failed to mark cooldown for {cooldown_key}: {_cd_e}")
                return resp
        # No lock key context -> legacy path
        return self._execute_broker_call(account, final_lot, sl_price, tp_price)

    def _execute_broker_call(self, account: Account, final_lot, sl_price, tp_price) -> dict:
        conn = self._get_connector(account)
        if account.platform == "MT5":
            limit_price_float = (
                float(self.data["limit_price"]) if self.data.get("limit_price") is not None else None
            )
            resp = conn.place_trade(
                symbol=self.data["symbol"],
                lot_size=final_lot,
                direction=self.data["direction"],
                stop_loss=sl_price,
                take_profit=tp_price,
                order_type=self.data.get("order_type", "MARKET"),
                limit_price=limit_price_float,
            )
            if resp.get("status") == "filled":
                opened_pos_ticket = resp.get("opened_position_ticket")
                if opened_pos_ticket:
                    pos_details = conn.get_position_by_ticket(opened_pos_ticket)
                    if "error" in pos_details:
                        logger.warning(
                            f"Could not fetch details for directly provided ticket {opened_pos_ticket}: {pos_details['error']}."
                        )
                        pos_details = {}
                    resp["position_info"] = pos_details
                else:
                    resp["position_info"] = {}
            return resp
        else:  # cTrader
            resp = conn.place_order(
                symbol=self.data["symbol"],
                volume=final_lot,
                trade_side=self.data["direction"],
                order_type=self.data["order_type"],
                limit_price=self.data.get("limit_price"),
                time_in_force=self.data.get("time_in_force", "GTC"),
                stop_loss=sl_price,
                take_profit=tp_price,
            )
            return resp

    def persist(self, account: Account, resp: dict, final_lot, sl_price, tp_price):
        """
        Save the Order and, if filled, the Trade and any ProfitTarget legs.
        """
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
        if resp.get("status") == "filled":
            raw_position_info = resp.get("position_info", {})

            # Prepare data for Trade object creation, using fallbacks if necessary
            trade_lot_size = final_lot
            trade_entry_price = resp.get(
                "price"
            )  # Default to price from place_trade (tick.ask/bid)
            trade_sl = sl_price
            trade_tp = tp_price

            if raw_position_info and not raw_position_info.get("error"):
                trade_lot_size = raw_position_info.get("volume", final_lot)
                # Override entry_price if available from fetched position details
                if raw_position_info.get("price_open") is not None:
                    trade_entry_price = raw_position_info.get("price_open")
                trade_sl = raw_position_info.get("sl", sl_price)
                trade_tp = raw_position_info.get("tp", tp_price)
            elif raw_position_info.get("error"):
                logger.warning(
                    f"--- trades/services.py (persist): position_info has error: {raw_position_info.get('error')}. Using calculated/default values for some trade details."
                )

            # Determine the position_id for the Trade record
            db_trade_position_id = None
            # For MT5 Market orders, user confirmed that resp["order_id"] (the order ticket) IS the position_id.
            if (
                account.platform == "MT5"
                and self.data.get("order_type", "").upper() == "MARKET"
            ):
                db_trade_position_id = resp.get("order_id")
                logger.info(
                    f"--- trades/services.py (persist): Using order_id {db_trade_position_id} as Trade.position_id for MT5 MARKET order."
                )
            elif raw_position_info and not raw_position_info.get("error"):
                # For cTrader or non-market MT5, or if MT5 market order assumption is wrong, use ticket from fetched position_info
                db_trade_position_id = raw_position_info.get("ticket")
                logger.info(
                    f"--- trades/services.py (persist): Using ticket {db_trade_position_id} from position_info as Trade.position_id."
                )

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
                entry_price=(
                    Decimal(str(trade_entry_price))
                    if trade_entry_price is not None
                    else None
                ),
                stop_loss=Decimal(str(trade_sl)),
                profit_target=Decimal(str(trade_tp)),
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
            out.update(
                {
                    "trade_id": str(trade.id),
                    "entry_price": float(trade.entry_price),
                }
            )
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

    profit = None
    # This variable helps decide if we should proceed to update our DB record
    # In some cases, we might want to close our record even if broker interaction fails or is skipped.
    # However, for MT5, if broker interaction fails, an exception is raised, stopping execution.
    # So, reaching the DB update part implies broker success for MT5.

    if trade.account.platform == "MT5":
        try:
            mt5_account = trade.account.mt5_account
        except MT5Account.DoesNotExist:
            raise TradeValidationError(
                "No linked MT5 account found for this trade's account."
            )

        client = MT5APIClient(
            base_url=settings.MT5_API_BASE_URL,
            account_id=mt5_account.account_number,
            password=mt5_account.encrypted_password,
            broker_server=mt5_account.broker_server,
            internal_account_id=str(trade.account.id),
        )

        mt5_position_ticket_to_close = trade.position_id
        if not mt5_position_ticket_to_close:
            logger.warning(
                f"Trade {trade.id} has no position_id. Attempting to use order_id {trade.order_id} for closure."
            )
            mt5_position_ticket_to_close = trade.order_id

        if not mt5_position_ticket_to_close:
            raise TradeValidationError(
                f"Cannot close trade {trade.id}: Missing MT5 position ticket (position_id or order_id)."
            )

        client.close_trade(
            ticket=mt5_position_ticket_to_close,
            volume=float(trade.remaining_size),
            symbol=trade.instrument,
        )

        # After successful closure, synchronize with the platform to get the final P/L
        try:
            sync_result = synchronize_trade_with_platform(
                trade_id=trade.id, existing_connector=client
            )
            if sync_result.get("error"):
                logger.error(f"Error during post-close synchronization: {sync_result['error']}")
            else:
                logger.info(f"Post-close synchronization for trade {trade.id} successful.")
        except (BrokerAPIError, BrokerConnectionError, TradeSyncError) as e:
            logger.critical(f"Trade {trade.id} closed on MT5, but DB sync failed: {e}")
            pass

    elif trade.account.platform == "cTrader":
        raise BrokerAPIError("cTrader close not implemented yet.")
    else:
        raise APIException("Unsupported trading platform.")

    # Refresh the instance from the DB to get the latest state after sync
    trade.refresh_from_db()

    # Tag final close if not set by sync
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
                # Best-effort inference using last price
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


def partially_close_trade(user, trade_id: UUID, volume_to_close: Decimal) -> dict:
    """
    Partially closes an open trade, performs platform-specific actions,
    and updates the database.
    """
    trade = get_object_or_404(Trade, id=trade_id)

    if trade.account.user != user:
        raise PermissionDenied("Unauthorized to partially close this trade.")

    if trade.trade_status != "open":
        raise ValidationError("Trade is not open, cannot partially close.")

    if not (Decimal("0.01") <= volume_to_close < trade.remaining_size):
        raise ValidationError(
            f"Volume to close ({volume_to_close}) must be between 0.01 and "
            f"less than remaining size ({trade.remaining_size}). "
            f"For full closure, use the close trade endpoint."
        )

    connector = None  # Initialize connector

    if trade.account.platform == "MT5":
        try:
            mt5_account = trade.account.mt5_account
        except MT5Account.DoesNotExist:
            raise TradeValidationError(
                "No linked MT5 account found for this trade's account."
            )

        client = MT5APIClient(
            base_url=settings.MT5_API_BASE_URL,
            account_id=mt5_account.account_number,
            password=mt5_account.encrypted_password,
            broker_server=mt5_account.broker_server,
            internal_account_id=str(trade.account.id),
        )

        if not trade.position_id:
            raise TradeValidationError(
                f"Cannot partially close trade {trade.id}: Missing MT5 position ticket (position_id)."
            )

        client.close_trade(
            ticket=trade.position_id,
            volume=float(volume_to_close),
            symbol=trade.instrument,
        )

        # Successfully issued partial close command to broker
        # Now, synchronize to get the deal and update trade state
        try:
            synchronize_trade_with_platform(
                trade_id=trade.id, existing_connector=connector
            )
        except (BrokerAPIError, BrokerConnectionError, TradeSyncError) as e:
            # This is problematic: broker action succeeded, but DB sync failed.
            # Log this error thoroughly. The trade state in DB might be stale.
            # For now, we'll raise an exception, but a more robust solution might involve
            # retrying sync or flagging the trade for manual review.
            logger.critical(
                f"Trade {trade.id} partially closed on MT5, but DB sync failed: {e}"
            )
            raise TradeSyncError(
                f"Partially closed on platform, but DB sync failed: {e}. Please check trade status."
            )

        # Find the latest order related to this trade to tag P/L of the closed portion
        # This assumes synchronize_trade_with_platform created an Order for the partial close deal.
        # We sort by filled_at or created_at to get the most recent one.
        closed_portion_order = (
            Order.objects.filter(trade=trade, status=Order.Status.FILLED)
            .order_by("-filled_at", "-created_at")
            .first()
        )

        # Default tagging for strategy-driven partial close
        if closed_portion_order and not closed_portion_order.close_reason:
            closed_portion_order.close_reason = "STRATEGY_EXIT"
            closed_portion_order.close_subreason = (
                "EXIT_LONG" if (trade.direction or "").upper() == "BUY" else "EXIT_SHORT"
            )
            closed_portion_order.save(update_fields=["close_reason", "close_subreason"])

        # Refresh trade instance from DB after sync
        trade.refresh_from_db()

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

    elif trade.account.platform == "cTrader":
        raise APIException("cTrader partial close not implemented yet.")
    else:
        raise APIException(f"Unsupported trading platform: {trade.account.platform}")


def synchronize_trade_with_platform(
    trade_id: UUID, existing_connector: MT5APIClient = None
):  # Add existing_connector
    """
    Synchronizes a single trade record with the trading platform (e.g., MT5).
    Fetches the latest deals, updates order history, remaining size, status, and P/L.
    Can use an existing MT5APIClient instance if provided.
    """
    try:
        trade_instance = get_object_or_404(Trade, id=trade_id)
    except Trade.DoesNotExist:
        raise TradeValidationError(f"Trade with id {trade_id} not found.")

    sync_data = None
    platform_name = trade_instance.account.platform
    connector_to_use = existing_connector

    if platform_name == "MT5":
        if not connector_to_use:
            try:
                mt5_account_details = MT5Account.objects.get(
                    account=trade_instance.account
                )
            except MT5Account.DoesNotExist:
                raise TradeValidationError(
                    f"MT5Account details not found for account {trade_instance.account.id}."
                )

            connector_to_use = MT5APIClient(
                base_url=settings.MT5_API_BASE_URL,
                account_id=mt5_account_details.account_number,
                password=mt5_account_details.encrypted_password,
                broker_server=mt5_account_details.broker_server,
                internal_account_id=str(trade_instance.account.id),
            )

        if not connector_to_use:
            raise TradeValidationError("MT5 connector not available.")

        if (
            hasattr(connector_to_use, "account_id")
            and hasattr(trade_instance.account, "mt5_account")
            and connector_to_use.account_id
            != trade_instance.account.mt5_account.account_number
        ):
            logger.warning(
                f"synchronize_trade_with_platform called with connector for account {connector_to_use.account_id}, "
                f"but trade {trade_instance.id} belongs to account {trade_instance.account.mt5_account.account_number}. This might lead to issues."
            )

        if not trade_instance.position_id:
            raise TradeValidationError(
                f"Trade {trade_instance.id} does not have a position_id. Cannot sync with MT5."
            )

        sync_data = connector_to_use.fetch_trade_sync_data(
            position_id=trade_instance.position_id,
            instrument_symbol=trade_instance.instrument,
        )

    elif platform_name == "cTrader":
        # ctrade_account_details = CTraderAccount.objects.get(account=trade_instance.account)
        # connector = CTraderClient(ctrade_account_details)
        # sync_data = connector.fetch_trade_sync_data(...)
        raise BrokerAPIError("cTrader synchronization not yet implemented.")
    else:
        raise TradeValidationError(f"Unsupported platform: {platform_name}")

    if not sync_data:
        raise TradeSyncError("Failed to retrieve sync data from platform.")

    if sync_data.get("error_message"):
        raise BrokerAPIError(f"Platform error: {sync_data.get('error_message')}")

    # 1. Update/Create Order records from sync_data["deals"] with closure tagging
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
                try:
                    close_price = last_close_order.filled_price if last_close_order else None
                    close_price_dec = Decimal(str(close_price)) if close_price is not None else None
                except Exception:
                    close_price_dec = None
                inferred = _infer_close_reason(trade_instance, close_price_dec) if close_price_dec is not None else None
                trade_instance.close_reason = inferred
                trade_instance.close_subreason = None

    try:
        trade_instance.save()
        return {
            "message": f"Trade {trade_instance.id} synchronized successfully.",
            "trade_id": str(trade_instance.id),
            "status": trade_instance.trade_status,
            "remaining_size": str(trade_instance.remaining_size),
        }
    except Exception as e:
        raise TradeSyncError(f"Failed to save synchronized trade {trade_instance.id}: {str(e)}")


# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
#                  UPDATE TRADE STOP LOSS / TAKE PROFIT
# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++


def update_trade_protection_levels(
    user, trade_id: UUID, new_stop_loss: Decimal = None, new_take_profit: Decimal = None
) -> dict:
    """
    Updates the stop loss and/or take profit for an open trade on the platform and in the database.
    At least one of new_stop_loss or new_take_profit must be provided.
    """
    trade = get_object_or_404(Trade, id=trade_id)

    if trade.account.user != user:
        raise PermissionDenied("Unauthorized to update this trade's protection levels.")

    if trade.trade_status != "open":
        raise ValidationError("Protection levels can only be updated for open trades.")

    # This function will now ONLY handle take_profit updates.
    # SL updates are handled by update_trade_stop_loss_globally.
    if new_take_profit is None:
        raise ValidationError("new_take_profit must be provided.")

    if new_stop_loss is not None:
        # This function should not be used for SL updates anymore.
        raise ValidationError(
            "This endpoint is only for updating take profit. Use the specific SL update endpoint for stop loss changes."
        )

    account = trade.account
    connector = None
    platform_response = None

    # Determine current SL and TP to pass to modify_position_protection
    # If a new value is provided, use that; otherwise, use the existing value from the trade object.
    # Ensure values are float for MT5Connector, or 0.0 if None (MT5 uses 0.0 for no SL/TP).

    # Fetch live position details to get current SL/TP from platform if not updating them
    # This ensures we send the most current values for the unmodified protection level.
    current_sl_from_platform = trade.stop_loss  # We need current SL to send to platform
    current_tp_from_platform = trade.profit_target  # Fallback if platform fetch fails

    if account.platform == "MT5":
        try:
            mt5_account = account.mt5_account
        except MT5Account.DoesNotExist:
            raise TradeValidationError(
                "No linked MT5 account found for this trade's account."
            )

        client = MT5APIClient(
            base_url=settings.MT5_API_BASE_URL,
            account_id=mt5_account.account_number,
            password=mt5_account.encrypted_password,
            broker_server=mt5_account.broker_server,
            internal_account_id=str(account.id),
        )

        if not trade.position_id:
            raise TradeValidationError(
                f"Trade {trade.id} does not have a position_id. Cannot update protection on MT5."
            )

        position_details = client.get_position_by_ticket(ticket=int(trade.position_id))
        current_sl_from_platform = Decimal(str(position_details.get("sl", 0.0)))

    # Values to send to the broker
    # SL will be the current SL from the platform (or DB if platform fetch failed)
    # TP will be the new_take_profit
    sl_to_send = float(
        current_sl_from_platform if current_sl_from_platform is not None else 0.0
    )
    tp_to_send = float(
        new_take_profit
    )  # new_take_profit is guaranteed to be non-None here

    if account.platform == "MT5":  # Re-check platform for sending command
        platform_response = client.modify_position_protection(
            position_id=int(trade.position_id),
            symbol=trade.instrument,
            stop_loss=sl_to_send,
            take_profit=tp_to_send,
        )

    elif account.platform == "cTrader":
        raise BrokerAPIError("cTrader take profit update not implemented yet.")
    else:
        raise APIException(f"Unsupported platform: {account.platform}")

    # Update Trade Model in Database
    trade.profit_target = new_take_profit
    trade.save(update_fields=["profit_target"])

    return {
        "message": "Trade take profit updated successfully.",
        "trade_id": str(trade.id),
        "new_take_profit": float(trade.profit_target),
        "platform_response": platform_response,
    }


def update_trade_stop_loss_globally(
    user,
    trade_id: UUID,
    sl_update_type: str,  # "breakeven", "distance_pips", "distance_price", "specific_price"
    value: Decimal = None,
    specific_price: Decimal = None,
) -> dict:
    """
    Updates the stop loss for an open trade based on the specified update type.
    Platform-agnostic, currently implements MT5 logic.
    """
    trade = get_object_or_404(Trade, id=trade_id)

    if trade.account.user != user:
        raise PermissionDenied("Unauthorized to update this trade's stop loss.")

    if trade.trade_status != "open":
        raise ValidationError("Stop loss can only be updated for open trades.")

    account = trade.account
    new_stop_loss_price = None
    current_tp_price = None  # Will be fetched for MT5

    # 1. Instantiate Connector and Connect
    connector = None
    if account.platform == "MT5":
        try:
            mt5_account = account.mt5_account
        except MT5Account.DoesNotExist:
            raise TradeValidationError(
                "No linked MT5 account found for this trade's account."
            )

        client = MT5APIClient(
            base_url=settings.MT5_API_BASE_URL,
            account_id=mt5_account.account_number,
            password=mt5_account.encrypted_password,
            broker_server=mt5_account.broker_server,
            internal_account_id=str(account.id),
        )

        if not trade.position_id:
            raise TradeValidationError(
                f"Trade {trade.id} does not have a position_id. Cannot update SL on MT5."
            )

        position_details = client.get_position_by_ticket(ticket=int(trade.position_id))
        current_tp_price = Decimal(str(position_details.get("tp", 0.0)))

    elif account.platform == "cTrader":
        # ct_acc = get_object_or_404(CTraderAccount, account=account)
        # connector = CTraderClient(ct_acc)
        # # cTrader specific connection/auth if needed
        raise BrokerAPIError("cTrader stop loss update not implemented yet.")
    else:
        raise APIException(f"Unsupported platform: {account.platform}")

    # 2. Calculate New Stop Loss Price
    if sl_update_type == "breakeven":
        if trade.entry_price is None:
            raise ValidationError(
                "Cannot set SL to breakeven as entry price is not available."
            )
        new_stop_loss_price = trade.entry_price
    elif sl_update_type == "specific_price":
        if specific_price is None:
            raise ValidationError(
                "specific_price must be provided for 'specific_price' update type."
            )
        new_stop_loss_price = specific_price
    elif sl_update_type in ["distance_pips", "distance_price"]:
        if value is None:
            raise ValidationError(f"A 'value' must be provided for '{sl_update_type}'.")

        live_price_data = client.get_live_price(symbol=trade.instrument)
        current_market_price = None
        if trade.direction == "BUY":  # Corrected
            current_market_price = Decimal(
                str(live_price_data["bid"])
            )  # SL for BUY is based on BID
        elif trade.direction == "SELL":  # Corrected
            current_market_price = Decimal(
                str(live_price_data["ask"])
            )  # SL for SELL is based on ASK
        else:
            raise ValidationError(f"Invalid trade direction: {trade.direction}")

        price_offset = Decimal(str(value))

        if sl_update_type == "distance_pips":
            symbol_info = client.get_symbol_info(symbol=trade.instrument)
            pip_size = Decimal(str(symbol_info["pip_size"]))
            price_offset = price_offset * pip_size

        if trade.direction == "BUY":  # Corrected
            new_stop_loss_price = current_market_price - price_offset
        elif trade.direction == "SELL":  # Corrected
            new_stop_loss_price = current_market_price + price_offset
        # No else needed here as validated above

        symbol_info_for_rounding = client.get_symbol_info(symbol=trade.instrument)
        # Inferring digits from tick_size for rounding
        tick_size_str = str(symbol_info_for_rounding.get("tick_size", "0.00001"))
        if "." in tick_size_str:
            num_digits = len(tick_size_str.split(".")[1])
        else:
            num_digits = 0  # Should not happen for forex/cfds

        new_stop_loss_price = new_stop_loss_price.quantize(
            Decimal("1e-" + str(num_digits))
        )

    else:
        raise ValidationError(f"Invalid sl_update_type: {sl_update_type}")

    if new_stop_loss_price is None:
        raise TradeValidationError("Failed to calculate new stop loss price.")

    # SL Rule: Cannot remove SL by setting to 0.0 if type is 'specific_price'
    if sl_update_type == "specific_price" and new_stop_loss_price == Decimal("0.0"):
        raise ValidationError(
            "Stop loss removal (setting to 0.0) is not allowed via this endpoint."
        )

    # SL Rule: New SL cannot be further than the existing one (trade.stop_loss from DB).
    if trade.stop_loss is not None and trade.stop_loss != Decimal(
        "0.0"
    ):  # Check if there's an existing, non-zero SL
        current_db_sl = trade.stop_loss
        if trade.direction == "BUY":
            if new_stop_loss_price < current_db_sl:
                raise ValidationError(
                    f"New stop loss ({new_stop_loss_price}) cannot be further (lower) than the current one ({current_db_sl}) for a BUY trade."
                )
        elif trade.direction == "SELL":
            if new_stop_loss_price > current_db_sl:
                raise ValidationError(
                    f"New stop loss ({new_stop_loss_price}) cannot be further (higher) than the current one ({current_db_sl}) for a SELL trade."
                )

    # 3. Execute SL Update on Broker
    modification_result = None
    if account.platform == "MT5":
        if not trade.position_id:
            raise TradeValidationError(
                f"Trade {trade.id} does not have a position_id. Cannot update SL on MT5."
            )

        modification_result = client.modify_position_protection(
            position_id=int(trade.position_id),
            symbol=trade.instrument,
            stop_loss=float(new_stop_loss_price),
            take_profit=float(current_tp_price),
        )

    # 4. Update Trade Model in Database
    trade.stop_loss = new_stop_loss_price
    # Potentially log the change or create a history record for SL modifications
    trade.save(update_fields=["stop_loss"])

    return {
        "message": "Stop loss updated successfully.",
        "trade_id": str(trade.id),
        "new_stop_loss": float(new_stop_loss_price),
        "platform_response": (
            modification_result if account.platform == "MT5" else "N/A"
        ),
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

    if order.account.platform == "MT5":
        try:
            mt5_account = order.account.mt5_account
        except MT5Account.DoesNotExist:
            raise TradeValidationError(
                "No linked MT5 account found for this order's account."
            )

        client = MT5APIClient(
            base_url=settings.MT5_API_BASE_URL,
            account_id=mt5_account.account_number,
            password=mt5_account.encrypted_password,
            broker_server=mt5_account.broker_server,
            internal_account_id=str(order.account.id),
        )

        if not order.broker_order_id:
            raise TradeValidationError(
                f"Cannot cancel order {order.id}: Missing broker_order_id."
            )

        cancel_result = client.cancel_order(order_ticket=int(order.broker_order_id))

        # Update order status in the database
        order.status = Order.Status.CANCELLED
        order.save(update_fields=["status"])

        return {
            "message": "Order canceled successfully.",
            "order_id": str(order.id),
            "platform_response": cancel_result,
        }

    elif order.account.platform == "cTrader":
        raise BrokerAPIError("cTrader order cancellation not implemented yet.")
    else:
        raise TradeValidationError(
            f"Unsupported trading platform: {order.account.platform}"
        )
