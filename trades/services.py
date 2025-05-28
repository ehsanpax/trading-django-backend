# trades/services.py
from decimal import Decimal
from django.shortcuts import get_object_or_404
from accounts.models import Account, MT5Account, CTraderAccount
from connectors.ctrader_client import CTraderClient
from mt5.services import MT5Connector
from risk.management import validate_trade_request, perform_risk_checks, fetch_risk_settings
from trading.models import Order, Trade, ProfitTarget
from uuid import uuid4
from .targets import derive_target_price
from trading.models import IndicatorData
from rest_framework.exceptions import ValidationError, APIException, PermissionDenied
from django.utils import timezone as django_timezone # Alias for django's timezone
from uuid import UUID
from datetime import datetime, timezone as dt_timezone # Import datetime's timezone as dt_timezone

def get_cached(symbol, tf, ind):
    row = (
        IndicatorData.objects
        .filter(symbol=symbol, timeframe=tf, indicator_type=ind)
        .order_by("-updated_at")
        .first()
    )
    return row.value if row else None

# snapshot what you want

class TradeService:
    def __init__(self, user, validated_data):
        self.user = user
        self.data = validated_data

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

        rv = validate_trade_request(
            account_id         = str(account.id),
            user               = self.user,
            symbol             = self.data["symbol"],
            trade_direction    = self.data["direction"],
            stop_loss_distance = self.data["stop_loss_distance"],
            take_profit_price  = float(self.data["take_profit"]),
            risk_percent       = float(self.data["risk_percent"]),
        )
        if "error" in rv:
            raise ValidationError(rv["error"])

        final_lot = rv["lot_size"]
        sl_price  = rv["stop_loss_price"]
        tp_price  = rv["take_profit_price"]

        # extra guard rails, just like the old view did
        rm = fetch_risk_settings(account.id)
        rc = perform_risk_checks(rm, Decimal(final_lot), self.data["symbol"], Decimal(self.data["risk_percent"]))
        if "error" in rc:
            raise ValidationError(rc["error"])

        return account, final_lot, sl_price, tp_price
    def _get_connector(self, account: Account):
        if account.platform == "MT5":
            mt5_acc = get_object_or_404(MT5Account, account=account)
            conn = MT5Connector(mt5_acc.account_number, mt5_acc.broker_server)
            login = conn.connect(mt5_acc.encrypted_password)
            if "error" in login:
                raise RuntimeError(login["error"])
            return conn

        if account.platform == "cTrader":
            ct_acc = get_object_or_404(CTraderAccount, account=account)
            return CTraderClient(ct_acc)

        raise RuntimeError(f"Unsupported platform: {account.platform}")

    def execute_on_broker(self, account: Account, final_lot, sl_price, tp_price) -> dict:
        """
        Actually place the order on MT5 or cTrader, then for MT5-filled trades
        immediately fetch the live position details.
        """
        conn = self._get_connector(account)

        if account.platform == "MT5":
            resp = conn.place_trade(
                symbol        = self.data["symbol"],
                lot_size      = final_lot,
                direction     = self.data["direction"],
                order_type    = self.data["order_type"],
                limit_price   = self.data.get("limit_price"),
                time_in_force = self.data.get("time_in_force", "GTC"),
                stop_loss     = sl_price,
                take_profit   = tp_price,
            )
            if "error" in resp:
                raise APIException(resp["error"])

            # if filled immediately, grab full position info
            if resp.get("status") == "filled":
                opened_pos_ticket_value = resp.get("opened_position_ticket")
                print(f"--- trades/services.py: Value of resp.get('opened_position_ticket'): {opened_pos_ticket_value} (type: {type(opened_pos_ticket_value)})")

                opened_pos_ticket = resp.get("opened_position_ticket") # Re-get for the variable, or use opened_pos_ticket_value
                pos_details_source = "get_position_by_order_id" # For logging

                if opened_pos_ticket: # This condition checks if opened_pos_ticket is truthy (not None, not 0)
                    print(f"--- trades/services.py: Direct opened_position_ticket from place_trade: {opened_pos_ticket}")
                    pos_details = conn.get_open_position_details_by_ticket(opened_pos_ticket)
                    pos_details_source = f"get_open_position_details_by_ticket (direct ticket: {opened_pos_ticket})"
                    
                    if "error" in pos_details:
                        print(f"Warning: Could not fetch details for directly provided ticket {opened_pos_ticket}: {pos_details['error']}. Falling back to get_position_by_order_id for order {resp.get('order_id')}.")
                        # Fallback to original method if direct fetch fails
                        pos_details = conn.get_position_by_order_id(resp["order_id"]) or {}
                        pos_details_source = f"get_position_by_order_id (fallback for order: {resp.get('order_id')})"
                    resp["position_info"] = pos_details
                else:
                    # opened_position_ticket was not in resp, fall back to original method
                    print(f"Warning: opened_position_ticket not found in place_trade response for order {resp.get('order_id')}. Using get_position_by_order_id.")
                    pos_details = conn.get_position_by_order_id(resp["order_id"]) or {}
                    pos_details_source = f"get_position_by_order_id (no direct ticket for order: {resp.get('order_id')})"
                    resp["position_info"] = pos_details
                
                print(f"--- trades/services.py: Position info for order {resp.get('order_id')} (source: {pos_details_source}): {resp['position_info']}")

        else:  # cTrader
            resp = conn.place_order(
                symbol        = self.data["symbol"],
                volume        = final_lot,
                trade_side    = self.data["direction"],
                order_type    = self.data["order_type"],
                limit_price   = self.data.get("limit_price"),
                time_in_force = self.data.get("time_in_force", "GTC"),
                stop_loss     = sl_price,
                take_profit   = tp_price,
            )
            if "error" in resp:
                raise APIException(resp["error"])
            # cTraderClient should already include resp["position_info"] when filled

        return resp

    def persist(self, account: Account, resp: dict, final_lot, sl_price, tp_price):
        """
        Save the Order and, if filled, the Trade and any ProfitTarget legs.
        """
        snapshot = {
        "RSI_M1": get_cached(self.data["symbol"], "M1", "RSI"),
        "ATR_M1": get_cached(self.data["symbol"], "M1", "ATR"),
        }
        # 1️⃣ Order row
        order = Order.objects.create(
            id              = uuid4(),
            account         = account,
            instrument      = self.data["symbol"],
            direction       = self.data["direction"],
            order_type      = self.data["order_type"],
            volume          = Decimal(final_lot),
            price           = (Decimal(self.data["limit_price"]) 
                               if self.data.get("limit_price") is not None else None),
            stop_loss       = Decimal(sl_price),
            take_profit     = Decimal(tp_price),
            time_in_force   = self.data.get("time_in_force", "GTC"),
            broker_order_id = resp["order_id"],
            status          = resp.get("status", "pending"),
        )

        trade = None
        if resp.get("status") == "filled":
            raw_position_info = resp.get("position_info", {})
            
            # Prepare data for Trade object creation, using fallbacks if necessary
            trade_lot_size = final_lot
            trade_entry_price = resp.get("price") # Default to price from place_trade (tick.ask/bid)
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
                 print(f"--- trades/services.py (persist): position_info has error: {raw_position_info.get('error')}. Using calculated/default values for some trade details.")
            
            # Determine the position_id for the Trade record
            db_trade_position_id = None
            # For MT5 Market orders, user confirmed that resp["order_id"] (the order ticket) IS the position_id.
            if account.platform == "MT5" and self.data.get("order_type", "").upper() == "MARKET":
                db_trade_position_id = resp.get("order_id") 
                print(f"--- trades/services.py (persist): Using order_id {db_trade_position_id} as Trade.position_id for MT5 MARKET order.")
            elif raw_position_info and not raw_position_info.get("error"):
                # For cTrader or non-market MT5, or if MT5 market order assumption is wrong, use ticket from fetched position_info
                db_trade_position_id = raw_position_info.get("ticket")
                print(f"--- trades/services.py (persist): Using ticket {db_trade_position_id} from position_info as Trade.position_id.")
            
            if db_trade_position_id is None:
                 print(f"Warning: Trade.position_id will be NULL for order {resp.get('order_id')}. Fetched position_info: {raw_position_info}")

            trade = Trade.objects.create(
                account         = account,
                instrument      = self.data["symbol"],
                direction       = self.data["direction"],
                lot_size        = Decimal(str(trade_lot_size)),
                remaining_size  = Decimal(str(trade_lot_size)),
                entry_price     = Decimal(str(trade_entry_price)) if trade_entry_price is not None else None,
                stop_loss       = Decimal(str(trade_sl)),
                profit_target   = Decimal(str(trade_tp)),
                trade_status    = "open",
                order_id        = resp["order_id"], 
                deal_id         = resp.get("deal_id"), 
                position_id     = db_trade_position_id, 
                risk_percent    = Decimal(self.data["risk_percent"]),
                projected_profit= Decimal(self.data["projected_profit"]),
                projected_loss  = Decimal(self.data["projected_loss"]),
                rr_ratio        = Decimal(self.data["rr_ratio"]),
                reason          = self.data.get("reason", ""),
                indicators      = snapshot
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
                    trade.entry_price,
                    cfg,
                    trade.direction   # ← now included
                )
                vol = (total * Decimal(str(leg["share"]))).quantize(Decimal("0.01"))
                ProfitTarget.objects.create(
                    trade         = trade,
                    rank          = leg["rank"],
                    target_price  = price,
                    target_volume = vol,
                )

        return order, trade

    def build_response(self, order: Order, trade: Trade) -> dict:
        """
        Prepare the final JSON shape for the view.
        """
        out = {
            "message"      : "Order accepted",
            "order_id"     : order.broker_order_id,
            "order_status" : order.status,
        }
        if trade:
            out.update({
                "trade_id"   : str(trade.id),
                "entry_price": float(trade.entry_price),
            })
        return out

def close_trade_globally(user, trade_id: UUID) -> dict:
    """
    Closes a trade, performs platform-specific actions, and updates the database.
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
            raise APIException("No linked MT5 account found for this trade's account.")

        connector = MT5Connector(mt5_account.account_number, mt5_account.broker_server)
        login_result = connector.connect(mt5_account.encrypted_password)
        if "error" in login_result:
            raise APIException(f"MT5 connection failed: {login_result['error']}")

        # Close the trade on MT5 platform first
        # The 'ticket' parameter for close_trade should be the position ticket.
        # Assuming trade.position_id stores the MT5 position ticket.
        # If trade.order_id is used for MT5 position ticket, use that.
        # Based on TradeService.persist, trade.position_id is the intended field.
        mt5_position_ticket_to_close = trade.position_id
        if not mt5_position_ticket_to_close:
            # Fallback if position_id is somehow not set, try order_id.
            # This might happen if the trade was created before position_id was reliably populated.
            print(f"Warning: Trade {trade.id} has no position_id. Attempting to use order_id {trade.order_id} for closure.")
            mt5_position_ticket_to_close = trade.order_id
        
        if not mt5_position_ticket_to_close:
            raise APIException(f"Cannot close trade {trade.id}: Missing MT5 position ticket (position_id or order_id).")

        close_result = connector.close_trade(
            ticket=mt5_position_ticket_to_close,
            volume=float(trade.remaining_size), 
            symbol=trade.instrument
        )

        if "error" in close_result:
            # Even if closure fails (e.g., already closed, no connection), 
            # we might still want to fetch historical deal data if the position_id is valid.
            # However, if close_trade itself fails due to connection, fetching deals will also fail.
            # For now, if close_trade reports an error, we raise it.
            # Consider more nuanced error handling if needed (e.g., if error indicates "already closed").
            raise APIException(f"MT5 trade closure command failed: {close_result['error']}")

        # After successful closure command, fetch final P/L details from historical deals
        # Use the same position_id that was targeted for closure.
        final_details = connector.get_closing_deal_details_for_position(position_id=mt5_position_ticket_to_close)
        
        if "error" in final_details:
            # Log this error, as the trade was closed on platform but we couldn't get final P/L.
            # This could happen if history_deals_get fails or no exit deals are found immediately.
            print(f"Warning: Trade {trade.id} (MT5 pos: {mt5_position_ticket_to_close}) closed on platform, "
                  f"but failed to retrieve final P/L details: {final_details['error']}. P/L will be recorded as 0.")
            profit = Decimal(0) # Default P/L if details can't be fetched post-closure
        else:
            # Summing up profit, commission, and swap for the net P/L
            profit = (
                Decimal(str(final_details.get("profit", 0))) +
                Decimal(str(final_details.get("commission", 0))) +
                Decimal(str(final_details.get("swap", 0)))
            )
            # Optionally, store raw profit, commission, swap in separate DB fields if available/needed.
            # trade.commission = Decimal(str(final_details.get("commission",0)))
            # trade.swap = Decimal(str(final_details.get("swap",0)))
            # The Trade model already has commission and swap fields, let's update them.
            trade.commission = Decimal(str(final_details.get("commission", trade.commission or 0)))
            trade.swap = Decimal(str(final_details.get("swap", trade.swap or 0)))


    elif trade.account.platform == "cTrader":
        # Consistent with original view, cTrader close is not implemented.
        # Raising APIException will result in a 500, but view can catch it for a 400.
        # For now, let service raise APIException.
        raise APIException("cTrader close not implemented yet.")
    else:
        raise APIException("Unsupported trading platform.")

    # Update the trade record in the database
    trade.trade_status = "closed"
    trade.closed_at = django_timezone.now()
    if profit is not None: # Profit should be a Decimal here
        trade.actual_profit_loss = profit
    trade.save()

    return {
        "message": "Trade closed successfully",
        "trade_id": str(trade.id),
        "actual_profit_loss": float(trade.actual_profit_loss if trade.actual_profit_loss is not None else 0)
    }

def synchronize_trade_with_platform(trade_id: UUID):
    """
    Synchronizes a single trade record with the trading platform (e.g., MT5).
    Fetches the latest deals, updates order history, remaining size, status, and P/L.
    """
    try:
        trade_instance = get_object_or_404(Trade, id=trade_id)
    except Trade.DoesNotExist:
        # Or raise custom error / log
        return {"error": f"Trade with id {trade_id} not found."}

    sync_data = None
    platform_name = trade_instance.account.platform

    if platform_name == "MT5":
        try:
            mt5_account_details = MT5Account.objects.get(account=trade_instance.account)
        except MT5Account.DoesNotExist:
            return {"error": f"MT5Account details not found for account {trade_instance.account.id}."}

        connector = MT5Connector(account_id=mt5_account_details.account_number, broker_server=mt5_account_details.broker_server)
        connect_result = connector.connect(password=mt5_account_details.encrypted_password)

        if connect_result.get("error"):
            # MT5Connector's connect method already calls mt5.initialize and mt5.login
            # No separate mt5.shutdown() is typically needed here unless connector doesn't manage it.
            # For now, assume connector handles its lifecycle or mt5.shutdown() is called by a higher layer if needed.
            return {"error": f"MT5 connection failed: {connect_result.get('error')}"}
        
        if not trade_instance.position_id:
            # mt5.shutdown() # Ensure shutdown if we exit early after successful connect
            return {"error": f"Trade {trade_instance.id} does not have a position_id. Cannot sync with MT5."}

        sync_data = connector.fetch_trade_sync_data(
            position_id=trade_instance.position_id,
            instrument_symbol=trade_instance.instrument
        )
        # Assuming MT5Connector methods that use mt5 leave it in a usable state or shutdown is handled by caller of this sync function.
        # For safety, if this is the end of MT5 interaction for this scope:
        # import MetaTrader5 as mt5_main # To avoid conflict if mt5 is used elsewhere
        # mt5_main.shutdown()
        # However, the MT5Connector itself initializes MT5. If multiple calls to sync happen,
        # repeated initialize/shutdown might be inefficient. This needs a strategy.
        # For now, let's assume the connector leaves MT5 initialized if it was,
        # and a higher-level process manages global MT5 shutdown if necessary.

    elif platform_name == "cTrader":
        # Placeholder for cTrader logic
        # ctrade_account_details = CTraderAccount.objects.get(account=trade_instance.account)
        # connector = CTraderClient(ctrade_account_details)
        # sync_data = connector.fetch_trade_sync_data(...)
        return {"error": "cTrader synchronization not yet implemented."}
    else:
        return {"error": f"Unsupported platform: {platform_name}"}

    if not sync_data:
        return {"error": "Failed to retrieve sync data from platform."}

    if sync_data.get("error_message"):
        return {"error": f"Platform error: {sync_data.get('error_message')}"}

    # Process sync_data - platform-agnostic part
    # 1. Update/Create Order records from sync_data["deals"]
    existing_broker_deal_ids = set(
        trade_instance.order_history.values_list('broker_deal_id', flat=True).exclude(broker_deal_id__isnull=True)
    )

    for deal_info in sync_data.get("deals", []):
        broker_deal_id = deal_info.get("ticket")
        if broker_deal_id and broker_deal_id not in existing_broker_deal_ids:
            Order.objects.create(
                account=trade_instance.account,
                instrument=deal_info.get("symbol"),
                direction=Order.Direction.BUY if deal_info.get("type") == 0 else Order.Direction.SELL, # MT5: 0 for Buy, 1 for Sell
                order_type=Order.OrderType.MARKET, # Deals are executions
                volume=deal_info.get("volume"), # Already Decimal from fetch_trade_sync_data
                price=deal_info.get("price"),   # Already Decimal
                status=Order.Status.FILLED,
                broker_order_id=deal_info.get("order"),
                broker_deal_id=broker_deal_id,
                filled_price=deal_info.get("price"),
                filled_volume=deal_info.get("volume"),
                filled_at=datetime.fromtimestamp(deal_info.get("time"), tz=dt_timezone.utc) if deal_info.get("time") else None,
                profit=deal_info.get("profit"), # Already Decimal from fetch_trade_sync_data
                commission=deal_info.get("commission"), # Already Decimal
                swap=deal_info.get("swap"), # Already Decimal
                broker_deal_reason_code=deal_info.get("reason"), # Integer reason code
                trade=trade_instance,
                # Note: SL/TP from original order might not be in deal_info.
                # If needed, would require more complex logic to trace back to original order.
            )
            existing_broker_deal_ids.add(broker_deal_id) # Add to set to prevent re-creation in same run

    # 2. Update Trade.remaining_size
    trade_instance.remaining_size = sync_data.get("platform_remaining_size", trade_instance.remaining_size)

    # 3. Update Trade status if closed
    if sync_data.get("is_closed_on_platform") and trade_instance.trade_status == "open":
        trade_instance.trade_status = "closed"
        
        latest_deal_ts = sync_data.get("latest_deal_timestamp")
        if latest_deal_ts:
            trade_instance.closed_at = datetime.fromtimestamp(latest_deal_ts, tz=dt_timezone.utc)
        else:
            # If no deals, but platform says closed, use current time. Unlikely scenario.
            trade_instance.closed_at = django_timezone.now() 

        # Calculate P/L
        final_profit = sync_data.get("final_profit", Decimal("0"))
        final_commission = sync_data.get("final_commission", Decimal("0"))
        final_swap = sync_data.get("final_swap", Decimal("0"))
        
        # Ensure they are Decimals if not None
        final_profit = final_profit if final_profit is not None else Decimal("0")
        final_commission = final_commission if final_commission is not None else Decimal("0")
        final_swap = final_swap if final_swap is not None else Decimal("0")

        trade_instance.actual_profit_loss = final_profit + final_commission + final_swap
    
    try:
        trade_instance.save()
        return {
            "message": f"Trade {trade_instance.id} synchronized successfully.",
            "trade_id": str(trade_instance.id),
            "status": trade_instance.trade_status,
            "remaining_size": str(trade_instance.remaining_size)
        }
    except Exception as e:
        # Log error e
        return {"error": f"Failed to save synchronized trade {trade_instance.id}: {str(e)}"}

def update_trade_stop_loss_globally(user,
                                    trade_id: UUID,
                                    sl_update_type: str,
                                    value: Decimal = None, # For distance_pips or distance_price
                                    specific_price: Decimal = None) -> dict:
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
    current_tp_price = None # Will be fetched for MT5

    # 1. Instantiate Connector and Connect
    connector = None
    if account.platform == "MT5":
        try:
            mt5_account = account.mt5_account
        except MT5Account.DoesNotExist:
            raise APIException("No linked MT5 account found for this trade's account.")
        
        connector = MT5Connector(mt5_account.account_number, mt5_account.broker_server)
        login_result = connector.connect(mt5_account.encrypted_password)
        if "error" in login_result:
            raise APIException(f"MT5 connection failed: {login_result['error']}")
        
        # Fetch current position details to get current TP for MT5
        if not trade.position_id:
            raise APIException(f"Trade {trade.id} does not have a position_id. Cannot update SL on MT5.")
        
        position_details = connector.get_open_position_details_by_ticket(position_ticket=int(trade.position_id))
        if "error" in position_details:
            raise APIException(f"Failed to fetch current position details from MT5: {position_details['error']}")
        current_tp_price = Decimal(str(position_details.get("tp", 0.0))) # MT5 uses 0.0 if no TP

    elif account.platform == "cTrader":
        # ct_acc = get_object_or_404(CTraderAccount, account=account)
        # connector = CTraderClient(ct_acc)
        # # cTrader specific connection/auth if needed
        raise APIException("cTrader stop loss update not implemented yet.")
    else:
        raise APIException(f"Unsupported platform: {account.platform}")

    # 2. Calculate New Stop Loss Price
    if sl_update_type == "breakeven":
        if trade.entry_price is None:
            raise ValidationError("Cannot set SL to breakeven as entry price is not available.")
        new_stop_loss_price = trade.entry_price
    elif sl_update_type == "specific_price":
        if specific_price is None:
            raise ValidationError("specific_price must be provided for 'specific_price' update type.")
        new_stop_loss_price = specific_price
    elif sl_update_type in ["distance_pips", "distance_price"]:
        if value is None:
            raise ValidationError(f"A 'value' must be provided for '{sl_update_type}'.")

        live_price_data = connector.get_live_price(symbol=trade.instrument)
        if "error" in live_price_data:
            raise APIException(f"Could not fetch live price for {trade.instrument}: {live_price_data['error']}")

        current_market_price = None
        if trade.direction == "BUY": # Corrected
            current_market_price = Decimal(str(live_price_data["bid"])) # SL for BUY is based on BID
        elif trade.direction == "SELL": # Corrected
            current_market_price = Decimal(str(live_price_data["ask"]))  # SL for SELL is based on ASK
        else:
            raise ValidationError(f"Invalid trade direction: {trade.direction}")

        price_offset = Decimal(str(value))

        if sl_update_type == "distance_pips":
            symbol_info = connector.get_symbol_info(symbol=trade.instrument)
            if "error" in symbol_info:
                raise APIException(f"Could not fetch symbol info for {trade.instrument}: {symbol_info['error']}")
            
            pip_size = Decimal(str(symbol_info["pip_size"]))
            price_offset = price_offset * pip_size # Convert pips to price amount

        if trade.direction == "BUY": # Corrected
            new_stop_loss_price = current_market_price - price_offset
        elif trade.direction == "SELL": # Corrected
            new_stop_loss_price = current_market_price + price_offset
        # No else needed here as validated above
        
        # Round to symbol's precision (digits)
        symbol_info_for_rounding = connector.get_symbol_info(symbol=trade.instrument) # Re-fetch or use previous if available
        if "error" in symbol_info_for_rounding:
             raise APIException(f"Could not fetch symbol info for rounding: {symbol_info_for_rounding['error']}")
        num_digits = symbol_info_for_rounding.get('digits', 5) # Default to 5 if not found, though get_symbol_info doesn't return 'digits' directly
                                                              # MT5Connector.get_symbol_info returns pip_size and tick_size.
                                                              # We need to infer digits from pip_size or tick_size.
                                                              # Assuming pip_size = 10^-digits. So digits = -log10(pip_size)
                                                              # Or, more simply, use the number of decimal places in tick_size.
        
        # Inferring digits from tick_size for rounding
        tick_size_str = str(symbol_info_for_rounding.get("tick_size", "0.00001"))
        if '.' in tick_size_str:
            num_digits = len(tick_size_str.split('.')[1])
        else:
            num_digits = 0 # Should not happen for forex/cfds

        new_stop_loss_price = new_stop_loss_price.quantize(Decimal('1e-' + str(num_digits)))


    else:
        raise ValidationError(f"Invalid sl_update_type: {sl_update_type}")

    if new_stop_loss_price is None:
        raise APIException("Failed to calculate new stop loss price.")

    # Validate that the new SL is not further than the existing SL
    if trade.stop_loss is not None and trade.stop_loss != 0: # Check if there's an existing SL
        current_sl_price = trade.stop_loss
        if trade.direction == "BUY": # Corrected
            # For a BUY trade, a "further" SL is a lower price.
            # We want new_stop_loss_price >= current_sl_price
            if new_stop_loss_price < current_sl_price:
                raise ValidationError(f"New stop loss ({new_stop_loss_price}) cannot be further than the current one ({current_sl_price}) for a BUY trade.")
        elif trade.direction == "SELL": # Corrected
            # For a SELL trade, a "further" SL is a higher price.
            # We want new_stop_loss_price <= current_sl_price
            if new_stop_loss_price > current_sl_price:
                raise ValidationError(f"New stop loss ({new_stop_loss_price}) cannot be further than the current one ({current_sl_price}) for a SELL trade.")
        # No else needed here as trade.direction should be validated by model or earlier logic

    # 3. Execute SL Update on Broker
    modification_result = None # Initialize to handle cases where platform is not MT5
    if account.platform == "MT5":
        if not trade.position_id: # Should have been caught earlier
            raise APIException(f"Trade {trade.id} does not have a position_id. Cannot update SL on MT5.")

        # MT5Connector's modify_position_protection expects float
        modification_result = connector.modify_position_protection(
            position_id=int(trade.position_id),
            symbol=trade.instrument,
            stop_loss=float(new_stop_loss_price),
            take_profit=float(current_tp_price) # Pass current TP along
        )
        if "error" in modification_result:
            raise APIException(f"MT5 stop loss update failed: {modification_result['error']}")
    
    # 4. Update Trade Model in Database
    trade.stop_loss = new_stop_loss_price
    # Potentially log the change or create a history record for SL modifications
    trade.save(update_fields=["stop_loss"])

    return {
        "message": "Stop loss updated successfully.",
        "trade_id": str(trade.id),
        "new_stop_loss": float(new_stop_loss_price),
        "platform_response": modification_result if account.platform == "MT5" else "N/A"
    }
