# mt5/services.py
import MetaTrader5 as mt5
from trading.models import Trade
from datetime import datetime, timedelta, timezone
import time
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

        # Success payload
        return {
            "message":     "Trade executed successfully",
            "order_id":    result.order,
            "deal_id":     getattr(result, 'deal', None),
            "volume":      lot_size,
            "symbol":      symbol,
            "direction":   direction,
            "price":       price,
            # pending orders don’t fill immediately
            "status":      "filled" if order_type == "MARKET" else "pending",
        }


    def get_position_by_ticket(self, ticket: int) -> dict:
        """Fetch an open position by ticket (order ID)."""
        if mt5.terminal_info() is None:
            return {"error": "MT5 terminal is not running"}

        account_info = mt5.account_info()
        if not account_info or account_info.login != self.account_id:
            return {"error": "Not logged in to the correct MT5 account"}

        positions = mt5.positions_get(ticket=ticket)
        if positions is None:
            err_code, err_msg = mt5.last_error()
            return {"error": f"positions_get() failed: {err_code} - {err_msg}"}

        if not positions:
            return {"error": f"No open position found for ticket {ticket}"}

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
                "trade_id": trade_id,
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "price_open": pos.price_open,
                "profit": pos.profit,
                "time": pos.time,
                "direction": "SELL" if pos.type == 1 else "BUY"
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
            return {"error": f"Failed to close trade: {result.comment if result else 'no result'}"}

        return {"message": "Trade closed in MT5", "close_price": close_price}
    


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

    def get_closing_deal_details_for_position(self, position_id: int, days_history=2) -> dict:
        """
        Retrieves details of the closing deal(s) for a given position_id.
        It looks for deals that close the specified position (DEAL_ENTRY_OUT).
        Returns the combined profit, commission, swap, the reason of the primary closing deal,
        and the time of the latest deal associated with the position.

        :param position_id: The ID of the MT5 position.
        :param days_history: How many days back to check for deals.
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

        utc_to = datetime.now(timezone.utc)
        utc_from = utc_to - timedelta(days=days_history)
        
        # Fetch deals by position ID instead of order ID
        print(f"DEBUG MT5Service: Fetching history deals for position_id: {position_id} from {utc_from} to {utc_to}")
        deals = mt5.history_deals_get(utc_from, utc_to, position=position_id)

        if deals is None:
            err_code, err_msg = mt5.last_error()
            print(f"DEBUG MT5Service: history_deals_get() failed for position {position_id}: {err_code} - {err_msg}")
            return {"error": f"history_deals_get() failed for position {position_id}: {err_code} - {err_msg}"}

        if not deals:
            print(f"DEBUG MT5Service: No deals found for position {position_id} in the last {days_history} days.")
            return {"error": f"No deals found for position {position_id} in the last {days_history} days."}
        
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

        closed_by_sl = (closure_reason_code == mt5.DEAL_REASON_SL)
        closed_by_tp = (closure_reason_code == mt5.DEAL_REASON_TP)
        
        print(f"DEBUG MT5Service: Closing details for position {position_id}: P&L={total_profit}, Comm={total_commission}, Swap={total_swap}, Reason={closure_reason_code}, Time={close_time_dt.isoformat()}")

        return {
            "profit": total_profit, # Gross profit from deals
            "commission": total_commission,
            "swap": total_swap,
            "net_profit": total_profit + total_commission + total_swap, # Net financial impact
            "reason_code": closure_reason_code,
            "close_time": close_time_dt.isoformat(),
            "closed_by_sl": closed_by_sl,
            "closed_by_tp": closed_by_tp,
            "message": f"Closing details found for position {position_id}."
        }
