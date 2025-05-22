# mt5/services.py
import MetaTrader5 as mt5
from trading.models import Trade
from datetime import datetime, timedelta, timezone
import time
from decimal import Decimal
# import os # Good practice for path manipulations, though not strictly needed for this change.

class MT5Connector:
    """
    Handles connection, login, and trade execution for MT5.
    """
    def __init__(self, account_id: int, broker_server: str):
        self.account_id = account_id
        self.broker_server = broker_server
        
        # Construct the path to the specific terminal for this account
        self.terminal_path = rf"C:\MetaTrader 5\{self.account_id}\terminal64.exe"

        # Initialize MT5 with the specific terminal path
        if not mt5.initialize(path=self.terminal_path):
            init_error = mt5.last_error()
            print(f"MT5 Initialization Failed for terminal: {self.terminal_path}. Error: {init_error}")
            # Consider raising an exception or specific error handling
        else:
            print(f"MT5 Initialized Successfully for terminal: {self.terminal_path}")

    def connect(self, password: str) -> dict:
        """Log into MT5 if not already logged in, using the dedicated terminal instance."""
        
        terminal_info = mt5.terminal_info()
        if terminal_info is None:
            print(f"MT5 terminal_info is None. Attempting to re-initialize with path: {self.terminal_path}")
            if not mt5.initialize(path=self.terminal_path):
                # Log detailed error from mt5.last_error()
                init_error = mt5.last_error()
                error_msg = f"MT5 terminal is not running and re-initialization failed for path: {self.terminal_path}. Error: {init_error}"
                print(error_msg)
                return {"error": error_msg}
            terminal_info = mt5.terminal_info() # Check again
            if terminal_info is None:
                 error_msg = f"MT5 terminal is not running even after re-initialization for path: {self.terminal_path}."
                 print(error_msg)
                 return {"error": error_msg}

        account_info = mt5.account_info()
        # Check if already logged into the correct account *in the currently initialized terminal*
        if account_info and account_info.login == self.account_id:
            # This check assumes that mt5.account_info() correctly reflects the account
            # from the terminal specified by self.terminal_path.
            print(f"Already logged in as {self.account_id} in terminal {self.terminal_path}, skipping re-login.")
            return {"message": f"Already logged into MT5 account {self.account_id}"}

        print(f"Attempting login for account: {self.account_id} using terminal: {self.terminal_path}")
        
        # Shutdown any existing MT5 session and re-initialize with the specific path
        # This is crucial if another part of the application might have initialized MT5
        # without a path or with a different path.
        mt5.shutdown() 
        time.sleep(1)   # Wait one second for the shutdown to complete
        
        if not mt5.initialize(path=self.terminal_path): # Use the specific terminal path
            reinit_error = mt5.last_error()
            error_msg = f"MT5 reinitialization failed for terminal {self.terminal_path}: {reinit_error}"
            print(error_msg)
            return {"error": error_msg}
        else:
            print(f"MT5 reinitialized successfully for terminal: {self.terminal_path}")

        print(f"🔹 Logging into MT5 account: {self.account_id} on server: {self.broker_server} using terminal: {self.terminal_path}")
        login_status = mt5.login(self.account_id, password, self.broker_server)
        if not login_status:
            login_error_code, login_error_message = mt5.last_error()
            error_msg = f"Login failed for account {self.account_id} on terminal {self.terminal_path}. Error: {login_error_code} - {login_error_message}"
            print(error_msg)
            return {"error": error_msg}

        print(f"Successfully Logged into MT5 account {self.account_id} using terminal {self.terminal_path}")
        return {"message": f"Logged into MT5 account {self.account_id}"}

    def place_trade(
        self,
        symbol: str,
        lot_size: float,
        direction: str,
        order_type: str = "MARKET",
        limit_price: float = None,
        time_in_force: str = "GTC",
        stop_loss: float = None,
        take_profit: float = None,
    ) -> dict:
        """
        Executes a market trade or submits a pending order (limit/stop) on MT5.

        :param symbol: instrument symbol, e.g. "EURUSD"
        :param lot_size: size of the position in lots
        :param direction: "BUY" or "SELL"
        :param order_type: "MARKET", "LIMIT", or "STOP"
        :param limit_price: required price for LIMIT or STOP orders
        :param time_in_force: "GTC" or "DAY"
        :param stop_loss: absolute stop loss price
        :param take_profit: absolute take profit price
        :return: dict with execution result or error
        """

        # Ensure MT5 session is active
        if mt5.terminal_info() is None:
            return {"error": "⚠️ MT5 session lost before trade execution!"}

        # Ensure logged in to correct account
        account_info = mt5.account_info()
        if account_info is None or account_info.login != self.account_id:
            return {"error": "⚠️ MT5 session lost! Please reconnect before trading."}

                # 1️⃣ Fetch symbol precision & current tick
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            return {"error": f"⚠️ Symbol {symbol} not found or no info available"}
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return {"error": f"⚠️ No tick data for {symbol}"}

        direction  = direction.upper()
        order_type = order_type.upper()

        # 2️⃣ If pending order, ensure limit_price is provided, rounded and valid
        if order_type in ("LIMIT", "STOP"):
            if limit_price is None:
                return {"error": f"Missing 'limit_price' for {order_type} order"}

            # ⬇ Convert the string to float ⬇
            try:
                price_val = float(limit_price)
            except (TypeError, ValueError):
                return {"error": f"Invalid limit_price: {limit_price}"}

            # ⬇ Round to the symbol’s allowed number of decimal places ⬇
            limit_price = round(price_val, symbol_info.digits)

            # BUY‐LIMIT must be below ask; SELL‐LIMIT above bid
            if order_type == "LIMIT":
                if direction == "BUY" and limit_price >= tick.ask:
                    return {"error": (
                        f"Invalid price: BUY_LIMIT {limit_price} ≥ current ask {tick.ask}"
                    )}
                if direction == "SELL" and limit_price <= tick.bid:
                    return {"error": (
                        f"Invalid price: SELL_LIMIT {limit_price} ≤ current bid {tick.bid}"
                    )}

            # BUY‐STOP must be above ask; SELL‐STOP below bid
            if order_type == "STOP":
                if direction == "BUY" and limit_price <= tick.ask:
                    return {"error": (
                        f"Invalid price: BUY_STOP {limit_price} ≤ current ask {tick.ask}"
                    )}
                if direction == "SELL" and limit_price >= tick.bid:
                    return {"error": (
                        f"Invalid price: SELL_STOP {limit_price} ≥ current bid {tick.bid}"
                    )}

        # 3️⃣ Map action/type/price exactly as before, using our now‐validated limit_price
        if order_type == "MARKET":
            action = mt5.TRADE_ACTION_DEAL
            req_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
            price = tick.ask if direction == "BUY" else tick.bid
        elif order_type == "LIMIT":
            action = mt5.TRADE_ACTION_PENDING
            req_type = (
                mt5.ORDER_TYPE_BUY_LIMIT if direction == "BUY" 
                else mt5.ORDER_TYPE_SELL_LIMIT
            )
            price = limit_price
        else:  # STOP
            action = mt5.TRADE_ACTION_PENDING
            req_type = (
                mt5.ORDER_TYPE_BUY_STOP if direction == "BUY" 
                else mt5.ORDER_TYPE_SELL_STOP
            )
            price = limit_price

        # Map time_in_force
        tif_map = {
            "GTC": mt5.ORDER_TIME_GTC,
            "DAY": mt5.ORDER_TIME_DAY,
        }
        tif = tif_map.get(time_in_force.upper(), mt5.ORDER_TIME_GTC)

        # Build trade request
        trade_request = {
            "action":      action,
            "symbol":      symbol,
            "volume":      lot_size,
            "type":        req_type,
            "price":       price,
            "sl":          stop_loss or 0,
            "tp":          take_profit or 0,
            "deviation":   10,
            "magic":       0,
            "comment":     "Trade placed via API",
            "type_time":   tif,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # Send order
        result = mt5.order_send(trade_request)
        if result is None:
            err_code, err_msg = mt5.last_error()
            return {"error": f"❌ Trade execution failed: {err_code} - {err_msg}"}
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {"error": f"❌ Trade failed: {result.comment}"}

        # Construct success payload
        payload = {
            "message":   "Trade executed successfully",
            "order_id":  result.order,
            "deal_id":   getattr(result, 'deal', None),
            "volume":    lot_size,
            "symbol":    symbol,
            "direction": direction,
            "price":     price,
            "status":    "pending", # Default status
            "opened_position_ticket": None # Initialize to None, will be set for market orders
        }

        if order_type == "MARKET":
            payload["status"] = "filled"
            print(f"--- MT5Connector.place_trade (Market Order): OrderSendResult for order {result.order}: Deal={getattr(result, 'deal', 'N/A')}, Position (attr value)={getattr(result, 'position', 'N/A')}, Comment='{result.comment}', Retcode={result.retcode}")
            
            if result.order != 0: # Ensure the order ticket is valid
                payload["opened_position_ticket"] = result.order # Use order's own ticket
                print(f"--- MT5Connector.place_trade: Set opened_position_ticket to {result.order} (from result.order)")
            else:
                # This case should be rare for a successful order send
                print(f"--- MT5Connector.place_trade: result.order is 0, opened_position_ticket remains None.")
        # For pending orders, status remains "pending" and opened_position_ticket remains None as initialized.
        
        print(f"--- MT5Connector.place_trade: Final payload being returned: {payload}")
        return payload


    def get_open_position_details_by_ticket(self, position_ticket: int) -> dict:
        """Fetch details of a specific open position by its ticket."""
        if mt5.terminal_info() is None:
            return {"error": "MT5 terminal is not running"}

        account_info = mt5.account_info()
        if not account_info or account_info.login != self.account_id:
            return {"error": "Not logged in to the correct MT5 account"}

        positions = mt5.positions_get(ticket=position_ticket)
        if positions is None:
            err_code, err_msg = mt5.last_error()
            return {"error": f"positions_get(ticket={position_ticket}) failed: {err_code} - {err_msg}"}

        if not positions:
            return {"error": f"No open position found for ticket {position_ticket}"}

        pos = positions[0]
        return {
            "ticket": pos.ticket,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "price_open": pos.price_open,
            "sl": pos.sl,
            "tp": pos.tp,
            "profit": pos.profit,
            "comment": pos.comment,
            "time": pos.time
        }

    def get_position_by_order_id(self, order_id: int) -> dict:
        """Fetch an open position by the ticket of the order that created/modified it."""
        if mt5.terminal_info() is None:
            return {"error": "MT5 terminal is not running"}

        account_info = mt5.account_info()
        if not account_info or account_info.login != self.account_id:
            return {"error": "Not logged in to the correct MT5 account"}

        # Fetch deals related to the given order_id
        # Querying history deals for the last few days to ensure we capture recent orders.
        # Adjust timedelta if orders can be much older.
        from_date = datetime.now(timezone.utc) - timedelta(days=7)  # Look back 7 days from current time
        to_date = datetime.now(timezone.utc) + timedelta(hours=13) # Current time + 13 hours buffer
        deals = mt5.history_deals_get(from_date, to_date, order=order_id)

        if deals is None:
            # This means the call to history_deals_get failed, not necessarily no deals.
            err_code, err_msg = mt5.last_error()
            return {"error": f"Failed to retrieve deals for order_id {order_id}: {err_code} - {err_msg}"}

        if not deals:
            return {"error": f"No deals found for order_id {order_id}"}

        position_ticket = None
        MAX_RETRIES = 3
        RETRY_DELAY_SECONDS = 0.5  # Half a second delay

        for attempt in range(MAX_RETRIES):
            # Fetch deals in each attempt, in case they are updated
            current_deals = mt5.history_deals_get(from_date, to_date, order=order_id)

            if current_deals: # Check if current_deals is not None and not empty
                for deal in current_deals:
                    # We are looking for the position that was OPENED by this specific order_id.
                    # Such a deal should have deal.entry == mt5.DEAL_ENTRY_IN.
                    if deal.entry == mt5.DEAL_ENTRY_IN:
                        if deal.position_id != 0:
                            position_ticket = deal.position_id
                            break  # Found the position_id from an opening deal
                if position_ticket:
                    break  # Exit retry loop if position_ticket is found
            
            if attempt < MAX_RETRIES - 1:
                print(f"Attempt {attempt + 1}/{MAX_RETRIES}: DEAL_ENTRY_IN not found for order {order_id}, retrying in {RETRY_DELAY_SECONDS}s...")
                time.sleep(RETRY_DELAY_SECONDS)
            elif not position_ticket: # Last attempt and still not found
                # Fallback: If no DEAL_ENTRY_IN found after retries, try to get any position_id from any deal for this order.
                # This is less ideal but might catch cases where entry type is not IN but a position was still made.
                print(f"Warning: DEAL_ENTRY_IN not found for order {order_id} after {MAX_RETRIES} retries. Attempting fallback.")
                if current_deals: # Use deals from the last attempt
                    for deal_idx, deal_fallback in enumerate(current_deals):
                        if deal_fallback.position_id != 0:
                            position_ticket = deal_fallback.position_id
                            print(f"Fallback: Using position_id {position_ticket} from deal at index {deal_idx} (Ticket: {deal_fallback.ticket}, Order: {deal_fallback.order}, Entry: {deal_fallback.entry}, PosID: {deal_fallback.position_id}) for order_id {order_id}.")
                            break 
                if not position_ticket: # Still no position_ticket after fallback
                    return {"error": f"No opening deal (DEAL_ENTRY_IN) found and no fallback position_id available (no deals with non-zero position_id) for order_id {order_id} after {MAX_RETRIES} retries."}


        if position_ticket is None: # Should be caught by the error above, but as a safeguard.
            return {"error": f"Failed to determine position_id for order_id {order_id} after retries and fallback."}

        # Now fetch the open position using its ticket (which is position_ticket)
        positions = mt5.positions_get(ticket=position_ticket)
        if positions is None:
            # This means the call to positions_get failed
            err_code, err_msg = mt5.last_error()
            return {"error": f"positions_get(ticket={position_ticket}) failed: {err_code} - {err_msg}"}

        if not positions:
            # The position associated with this order_id is no longer open.
            return {"error": f"No open position found for position ticket {position_ticket} (derived from order_id {order_id})"}

        pos = positions[0]
        # The key "ticket" in the returned dict should refer to the position's ticket.
        return {
            "ticket": pos.ticket, # This is position_ticket
            "symbol": pos.symbol,
            "volume": pos.volume,
            "price_open": pos.price_open,
            "sl": pos.sl,
            "tp": pos.tp,
            "profit": pos.profit,
            "comment": pos.comment,
            "time": pos.time
        }

    def get_account_info(self) -> dict:
        """Fetches account balance, equity, and margin from MT5."""
        if mt5.terminal_info() is None:
            return {"error": "MT5 terminal is not running"}

        account_info = mt5.account_info()
        if not account_info:
            return {"error": "Failed to retrieve account info from MT5"}

        return {
            "balance": account_info.balance,
            "equity": account_info.equity,
            "margin": account_info.margin,
            "free_margin": account_info.margin_free,
            "leverage": account_info.leverage
        }

    def get_open_positions(self) -> dict:
        """Fetches all currently open positions in MT5."""
        if mt5.terminal_info() is None:
            return {"error": "MT5 terminal is not running"}

        positions = mt5.positions_get()
        if positions is None:
            err_code, err_msg = mt5.last_error()
            return {"error": f"positions_get() failed: {err_code} - {err_msg}"}

        open_positions = []
        for pos in positions:
            try:
                trade = Trade.objects.get(order_id=pos.ticket)
                trade_id = str(trade.id)
            except Trade.DoesNotExist:
                trade_id = None
            
            open_positions.append({
                "trade_id": trade_id, # Our internal UUID if matched
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "price_open": pos.price_open,
                "profit": pos.profit, # This is the live P/L from MT5 (floating P/L)
                "swap": pos.swap,     # Live Swap from MT5
                "commission": pos.commission, # Live Commission from MT5 (usually for entry/exit, not floating)
                "sl": pos.sl,         # Live Stop Loss from MT5
                "tp": pos.tp,         # Live Take Profit from MT5
                "time": pos.time,     # Open time (timestamp)
                "direction": "SELL" if pos.type == 1 else "BUY", # pos.type: 0 for buy, 1 for sell
                "comment": pos.comment, # Position comment
                "magic": pos.magic    # Position magic number
            })

        return {"open_positions": open_positions}



    def get_live_price(self, symbol: str) -> dict:
        """Fetch real-time price for a symbol from MT5."""
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            return {"symbol": symbol, "bid": tick.bid, "ask": tick.ask}
        return {"error": "Failed to retrieve price data"}

    def get_symbol_info(self, symbol: str) -> dict:
        """Fetches pip size, tick size, and contract size for a symbol."""
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            return {"error": f"Symbol {symbol} not found"}
        return {
            "symbol": symbol,
            "pip_size": 10 ** -symbol_info.digits,
            "tick_size": symbol_info.point,
            "contract_size": symbol_info.trade_contract_size
        }
    def close_trade(self, ticket: int, volume: float, symbol: str) -> dict:
        if mt5.terminal_info() is None:
            return {"error": "MT5 terminal is not running"}

        account_info = mt5.account_info()
        if not account_info or account_info.login != self.account_id:
            return {"error": "Not logged in to the correct MT5 account"}

        price_info = mt5.symbol_info_tick(symbol)
        if not price_info:
            return {"error": f"Price not available for {symbol}"}

        # Determine close price and order type
        position = mt5.positions_get(ticket=ticket)
        if not position:
            return {"error": f"No position found for ticket {ticket}"}

        pos = position[0]
        direction = "SELL" if pos.type == mt5.POSITION_TYPE_BUY else "BUY"
        close_price = price_info.bid if direction == "SELL" else price_info.ask
        order_type = mt5.ORDER_TYPE_SELL if direction == "SELL" else mt5.ORDER_TYPE_BUY

        close_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": close_price,
            "deviation": 10,
            "magic": 0,
            "comment": "Trade closed via API",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(close_request)

        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            return {"error": f"Failed to close trade: {result.comment if result else 'no result'}", "retcode": result.retcode if result else None}

        return {
            "message": "Trade closed in MT5",
            "close_price": close_price,
            "order_id": result.order, # The order ticket for the closing operation
            "deal_id": getattr(result, 'deal', None), # The deal ticket of the execution
            "retcode": result.retcode,
            "comment": result.comment
        }

    def modify_position_protection(self, position_id: int, symbol: str, stop_loss: float = None, take_profit: float = None) -> dict:
        """
        Modifies the Stop Loss and/or Take Profit of an open position.
        Pass 0 or None to a price level to remove it (if supported/desired).
        MT5 expects absolute price levels.
        """
        if mt5.terminal_info() is None:
            return {"error": "MT5 terminal is not running or not initialized."}
        
        account_info = mt5.account_info()
        if not account_info or account_info.login != self.account_id:
            return {"error": "Not logged in to the correct MT5 account for modifying position."}

        if stop_loss is None and take_profit is None:
            return {"error": "No stop_loss or take_profit value provided to modify."}

        # Ensure SL/TP are floats if provided, or 0.0 if None (MT5 uses 0.0 to remove SL/TP)
        sl_price = float(stop_loss) if stop_loss is not None else 0.0
        tp_price = float(take_profit) if take_profit is not None else 0.0
        
        # Basic validation: SL/TP should not be negative.
        # More advanced validation (e.g., SL must be below current price for BUY, etc.) can be added if needed.
        if sl_price < 0 or tp_price < 0:
            return {"error": "Stop Loss or Take Profit prices cannot be negative."}

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": position_id,
            "symbol": symbol,
            "sl": sl_price,
            "tp": tp_price,
        }

        print(f"Attempting to modify SL/TP for position {position_id} on {symbol}: SL={sl_price}, TP={tp_price}")
        result = mt5.order_send(request)

        if result is None:
            err_code, err_msg = mt5.last_error()
            error_message = f"order_send() failed for TRADE_ACTION_SLTP: {err_code} - {err_msg}"
            print(error_message)
            return {"error": error_message}

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            error_message = f"Failed to modify SL/TP for position {position_id}: {result.comment} (retcode: {result.retcode})"
            print(error_message)
            return {"error": error_message, "retcode": result.retcode, "comment": result.comment}

        success_message = f"Successfully modified SL/TP for position {position_id} on {symbol}."
        print(success_message)
        return {
            "message": success_message,
            "order_id": result.order, # The order ticket for the modification operation
            "request_id": result.request_id,
            "retcode": result.retcode,
            "comment": result.comment
        }
    


    def get_closed_deal_profit(self, ticket: int, max_retries=5, delay=2) -> dict:
        for attempt in range(max_retries):
            utc_from = datetime.now(timezone.utc) - timedelta(days=1)
            utc_to = datetime.now(timezone.utc)
            deals = mt5.history_deals_get(utc_from, utc_to)

            if deals:
                for deal in deals:
                    if deal.position_id == ticket:
                        print(f"✅ Profit found on retry {attempt+1}: {deal.profit}")
                        return {"profit": deal.profit}

            print(f"⏳ Retry {attempt+1}/{max_retries} — waiting for closed deal...")
            time.sleep(delay)

        return {"error": f"No closed deal found for ticket {ticket} after {max_retries} retries"}

    def get_latest_deal_ticket(self, order_ticket: int, max_retries=10, delay=1) -> int:
        """
        Attempts to retrieve the deal ticket corresponding to the given order ticket.
        It polls MT5's deal history for a matching deal (by order field) and returns its ticket.
        """
        from datetime import datetime, timedelta, timezone
        import time

        for attempt in range(max_retries):
            utc_from = datetime.now(timezone.utc) - timedelta(minutes=1)
            utc_to = datetime.now(timezone.utc)
            deals = mt5.history_deals_get(utc_from, utc_to)
            if deals:
                for d in deals:
                    if d.order == order_ticket:
                        print(f"✅ Found deal ticket {d.ticket} for order {order_ticket} on retry {attempt+1}")
                        return d.ticket
            print(f"⏳ Retry {attempt+1}/{max_retries} — waiting for deal ticket for order {order_ticket}...")
            time.sleep(delay)
        return None
    
    def get_closed_trade_profit(self, order_ticket: int, max_retries=10, delay=2) -> dict:
        """
        Polls MT5 history deals for all deals related to the given order_ticket (using the order filter)
        and sums up the profit, commission, and swap fields.
        """
        from datetime import datetime, timedelta, timezone
        import time

        for attempt in range(max_retries):
            utc_from = datetime.now(timezone.utc) - timedelta(days=1)
            utc_to = datetime.now(timezone.utc)
            # Use the order parameter to filter deals directly:
            deals = mt5.history_deals_get(utc_from, utc_to, order=order_ticket)
            if deals:
                total_profit = sum(deal.profit + deal.commission + deal.swap for deal in deals)
                print(f"✅ Total net profit for order {order_ticket} on attempt {attempt+1}: {total_profit}")
                return {"profit": total_profit}
            print(f"⏳ Retry {attempt+1}/{max_retries} — waiting for closed deals...")
            time.sleep(delay)
        return {"error": f"No closed deals found for order {order_ticket} after {max_retries} retries"}

    def get_closing_deal_details_for_position(self, position_id: int, days_history=7) -> dict: # Increased default to 7 days
        """
        Retrieves details of the closing deal(s) for a given position_id.
        It looks for deals that close the specified position (DEAL_ENTRY_OUT or DEAL_ENTRY_INOUT).
        Returns the combined profit, commission, swap, the reason of the primary closing deal,
        and the time of the latest deal associated with the position.

        :param position_id: The ID of the MT5 position.
        :param days_history: How many days back to check for deals. Default is 7 days.
        :return: A dict with 'profit', 'commission', 'swap', 'reason_code', 'close_time', 'closed_by_sl', 'closed_by_tp'
                 or an error dict.
        """
        if not position_id:
            return {"error": "position_id cannot be None or zero."}

        if mt5.terminal_info() is None:
            return {"error": "MT5 terminal is not running"}
        
        account_info = mt5.account_info()
        if not account_info or account_info.login != self.account_id:
            return {"error": "Not logged in to the correct MT5 account"}

        # MT5 deal times are UTC Unix timestamps. We query using a UTC window.
        # If the MT5 server filters history_deals_get date range based on its local server time,
        # a generous `days_history` ensures our UTC window covers the server's local day(s).
        # MT5 deal times are UTC Unix timestamps.
        # When a position_id is known, querying by position_id without a date range
        # should fetch all deals for that position's entire lifecycle.
        print(f"DEBUG MT5Service: Querying all history deals for position_id: {position_id}")
        
        deals = mt5.history_deals_get(position=position_id) # Query by position_id only

        if deals is None:
            err_code, err_msg = mt5.last_error()
            print(f"DEBUG MT5Service: history_deals_get(position={position_id}) call failed: {err_code} - {err_msg}")
            return {"error": f"history_deals_get(position={position_id}) call failed: {err_code} - {err_msg}"}

        if not deals:
            # This means no deals were ever associated with this position_id, or the ID is wrong.
            print(f"DEBUG MT5Service: No deals found for position_id {position_id} (queried without date range).")
            return {"error": f"No deals found for position_id {position_id}."}
        
        print(f"DEBUG MT5Service: Found {len(deals)} deals for position {position_id}.")

        # Filter for deals that represent an exit (DEAL_ENTRY_OUT) or a reversal (DEAL_ENTRY_INOUT).
        # For a given position, there should be entry deals (DEAL_ENTRY_IN) and exit deals.
        # We are interested in the exit deals for this position.
        exit_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT or d.entry == mt5.DEAL_ENTRY_INOUT]

        if not exit_deals:
            print(f"DEBUG MT5Service: No explicit exit deals (DEAL_ENTRY_OUT or DEAL_ENTRY_INOUT) found for position {position_id} among the {len(deals)} deals retrieved.")
            # This could mean the position was closed by merging, or other complex scenarios.
            # Or simply that the history hasn't fully propagated the closing deal with the correct entry type.
            # For now, if no explicit exit deal, we report it as an error for this function's purpose.
            return {"error": f"No explicit exit deal found for position {position_id}."}

        # Sum P/L, commission, swap from ALL deals related to this position_id.
        # This ensures that if there were multiple partial entries/exits or complex deal structures
        # for this single position ID, all their financial impacts are captured.
        total_profit = sum(d.profit for d in deals)
        total_commission = sum(d.commission for d in deals)
        total_swap = sum(d.swap for d in deals)
        
        # The primary closing event details (reason, time) should come from the latest exit deal.
        # If multiple exit deals (e.g. partial closures), the last one is the final closure.
        latest_exit_deal = sorted(exit_deals, key=lambda d: d.time, reverse=True)[0]
        
        closure_reason_code = latest_exit_deal.reason
        close_time_timestamp = latest_exit_deal.time 
        close_time_dt = datetime.fromtimestamp(close_time_timestamp, tz=timezone.utc)

        # Explicitly check against the known integer values for clarity in debugging
        # DEAL_REASON_SL = 3
        # DEAL_REASON_TP = 4
        is_sl_closure = (closure_reason_code == 3) # mt5.DEAL_REASON_SL
        is_tp_closure = (closure_reason_code == 4) # mt5.DEAL_REASON_TP
        
        print(f"DEBUG MT5Service: Closing details for position {position_id}: P&L={total_profit}, Comm={total_commission}, Swap={total_swap}, ReasonCode={closure_reason_code}, IsSL={is_sl_closure}, IsTP={is_tp_closure}, Time={close_time_dt.isoformat()}")

        return {
            "profit": total_profit, # Gross profit from deals
            "commission": total_commission,
            "swap": total_swap,
            "net_profit": total_profit + total_commission + total_swap, # Net financial impact
            "reason_code": closure_reason_code,
            "close_time": close_time_dt.isoformat(),
            "closed_by_sl": is_sl_closure, # Use the new boolean variables
            "closed_by_tp": is_tp_closure, # Use the new boolean variables
            "message": f"Closing details found for position {position_id}."
        }

    def fetch_trade_sync_data(self, position_id: int, instrument_symbol: str) -> dict:
        """
        Fetches all necessary data from MT5 for a given position to allow synchronization.
        This method does not modify the local database.
        Assumes MT5 is initialized and logged in via self.connect().
        """
        if mt5.terminal_info() is None:
            return {"error_message": "MT5 terminal is not running or not initialized."}
        
        account_info = mt5.account_info()
        if not account_info or account_info.login != self.account_id:
            return {"error_message": "Not logged in to the correct MT5 account for sync data fetch."}

        deals_data = []
        platform_remaining_size = Decimal('0.0')
        is_closed_on_platform = False
        latest_deal_timestamp = None
        final_profit = None
        final_commission = None
        final_swap = None
        error_message = None

        # Fetch all deals for the position
        mt5_deals_raw = mt5.history_deals_get(position=position_id)

        if mt5_deals_raw is None:
            err_code, err_msg = mt5.last_error()
            error_message = f"history_deals_get(position={position_id}) failed: {err_code} - {err_msg}"
            return {
                "deals": [], "is_closed_on_platform": False, "platform_remaining_size": Decimal('0.0'),
                "latest_deal_timestamp": None, "final_profit": None, "final_commission": None,
                "final_swap": None, "error_message": error_message
            }

        if not mt5_deals_raw:
            # No deals found, could mean position never existed or was cancelled before any deal.
            # Or, it's genuinely a new position with no deals yet.
            # For sync purposes, this means it's not closed by deals and has no P/L from deals.
            pass # Keep defaults: empty deals, not closed, zero P/L.

        # Process deals if any
        if mt5_deals_raw:
            # Sort deals by time to correctly calculate running volume and find latest deal
            sorted_deals = sorted(mt5_deals_raw, key=lambda d: d.time)
            latest_deal_timestamp = sorted_deals[-1].time

            for deal in sorted_deals:
                deals_data.append({
                    "ticket": deal.ticket,
                    "order": deal.order,
                    "time": deal.time,
                    "time_msc": deal.time_msc,
                    "type": deal.type, # ORDER_TYPE_BUY, ORDER_TYPE_SELL
                    "entry": deal.entry, # DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT
                    "magic": deal.magic,
                    "reason": deal.reason,
                    "position_id": deal.position_id,
                    "volume": Decimal(str(deal.volume)),
                    "price": Decimal(str(deal.price)),
                    "commission": Decimal(str(deal.commission)),
                    "swap": Decimal(str(deal.swap)),
                    "profit": Decimal(str(deal.profit)),
                    "symbol": deal.symbol,
                    "comment": deal.comment,
                    # "external_id": deal.external_id # if needed
                })
                
                deal_volume = Decimal(str(deal.volume))
                if deal.entry == mt5.DEAL_ENTRY_IN:
                    platform_remaining_size += deal_volume
                elif deal.entry == mt5.DEAL_ENTRY_OUT or deal.entry == mt5.DEAL_ENTRY_INOUT:
                    platform_remaining_size -= deal_volume
        
        # Check if position is closed on platform
        # Method 1: Based on remaining size from deals
        if platform_remaining_size <= Decimal('0.0') and mt5_deals_raw: # Must have deals to be closed by deals
            is_closed_on_platform = True
        
        # Method 2: Check active positions (more definitive if available)
        # Note: mt5.positions_get(ticket=position_id) is for specific position ticket, not generic position_id for history.
        # We need to get all positions for the symbol and check.
        open_mt5_positions = mt5.positions_get(symbol=instrument_symbol)
        if open_mt5_positions is None:
            err_code, err_msg = mt5.last_error()
            # This is an error in fetching positions, not necessarily that the specific position is closed
            print(f"Warning: positions_get(symbol={instrument_symbol}) failed: {err_code} - {err_msg}. Relying on deal volume for closure status.")
            # We don't set error_message here as we can still proceed with deal-based info.
        elif isinstance(open_mt5_positions, tuple):
            found_open_position = any(p.ticket == position_id for p in open_mt5_positions)
            if not found_open_position and mt5_deals_raw : # If not found among open positions, and there were deals
                is_closed_on_platform = True
            elif found_open_position: # Explicitly found open
                 is_closed_on_platform = False


        if is_closed_on_platform and mt5_deals_raw:
            final_profit = sum(Decimal(str(d.profit)) for d in mt5_deals_raw)
            final_commission = sum(Decimal(str(d.commission)) for d in mt5_deals_raw)
            final_swap = sum(Decimal(str(d.swap)) for d in mt5_deals_raw)

        return {
            "deals": deals_data,
            "is_closed_on_platform": is_closed_on_platform,
            "platform_remaining_size": platform_remaining_size,
            "latest_deal_timestamp": latest_deal_timestamp, # Unix timestamp (float or int)
            "final_profit": final_profit,
            "final_commission": final_commission,
            "final_swap": final_swap,
            "error_message": error_message
        }

# New code for historical trade reasons starts here
BROKER_DEAL_REASON_CODES_MT5 = {
    0: "Client Terminal",  # DEAL_REASON_CLIENT
    1: "Mobile Application",  # DEAL_REASON_MOBILE
    2: "Web Platform",  # DEAL_REASON_WEB
    3: "Expert Advisor/Script",  # DEAL_REASON_EXPERT
    4: "Stop Loss Hit",  # DEAL_REASON_SL
    5: "Take Profit Hit",  # DEAL_REASON_TP
    6: "Stop Out",  # DEAL_REASON_SO
    7: "Rollover",  # DEAL_REASON_ROLLOVER
    8: "Variation Margin",  # DEAL_REASON_VMARGIN
    9: "Instrument Split",  # DEAL_REASON_SPLIT
    10: "Corporate Action"  # DEAL_REASON_CORPORATE_ACTION
}

def get_mt5_deal_reason(order, trade_profit_targets):
    """
    Determines a human-readable reason for an MT5 deal (Order).

    :param order: The Order instance from trading.models.
    :param trade_profit_targets: A queryset or list of ProfitTarget instances related to the order's trade.
    :return: A string representing the deal reason.
    """
    if order.broker_deal_reason_code is None:
        return "Reason Not Specified"

    reason_code = order.broker_deal_reason_code

    if reason_code == 5:  # DEAL_REASON_TP (Take Profit)
        if order.filled_price is not None and trade_profit_targets:
            for pt in trade_profit_targets:
                # Ensure prices are compared as Decimals if they are Decimals
                # Add a small tolerance if necessary, but Decimal comparison should be exact
                if pt.target_price == order.filled_price and pt.status == 'hit':
                    return f"TP{pt.rank} Hit"
        # Fallback if no specific profit target matches or details are missing
        return BROKER_DEAL_REASON_CODES_MT5.get(reason_code, "Take Profit (General)")

    # For Stop Loss (reason_code == 4), the map already provides "Stop Loss Hit"
    # For other codes, use the map directly.
    return BROKER_DEAL_REASON_CODES_MT5.get(reason_code, f"Unknown Reason Code: {reason_code}")
