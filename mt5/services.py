# mt5/services.py
import MetaTrader5 as mt5
from trading.models import Trade
from datetime import datetime, timedelta, timezone
import time


class MT5Connector:
    """
    Handles connection, login, and trade execution for MT5.
    """
    def __init__(self, account_id: int, broker_server: str):
        self.account_id = account_id
        self.broker_server = broker_server

        if not mt5.initialize():
            print("MT5 Initialization Failed.")
        else:
            print("MT5 Initialized Successfully.")

    def connect(self, password: str) -> dict:
        """Log into MT5 if not already logged in."""
        terminal_info = mt5.terminal_info()
        if terminal_info is None:
            return {"error": "MT5 terminal is not running"}

        account_info = mt5.account_info()
        if account_info and account_info.login == self.account_id:
            print(f"Already logged in as {self.account_id}, skipping re-login.")
            return {"message": f"Already logged into MT5 account {self.account_id}"}

        print(f"Attempting login for account: {self.account_id}")
        login_status = mt5.login(self.account_id, password, self.broker_server)
        if not login_status:
            error_code, error_message = mt5.last_error()
            return {"error": f"Failed to log in to MT5: {error_code} - {error_message}"}

        print("Successfully Logged into MT5")
        return {"message": f"Logged into MT5 account {self.account_id}"}

    def place_trade(self, symbol: str, lot_size: float, direction: str, stop_loss: float, take_profit: float):
        """Executes a trade and ensures the session remains active."""
        print("🔹 Checking MT5 Session Before Trade...")
        if mt5.terminal_info() is None:
            return {"error": "⚠️ MT5 session lost before trade execution!"}

        # Ensure we are still logged in before placing a trade
        account_info = mt5.account_info()
        if account_info is None or account_info.login != self.account_id:
            return {"error": "⚠️ MT5 session lost! Please reconnect before trading."}

        order_type = mt5.ORDER_TYPE_BUY if direction.upper() == "BUY" else mt5.ORDER_TYPE_SELL
        price_info = mt5.symbol_info_tick(symbol)

        if not price_info:
            return {"error": f"⚠️ Symbol {symbol} not found or no tick info available"}

        price = price_info.ask if direction.upper() == "BUY" else price_info.bid
        print(f"Placing trade: symbol={symbol}, lot_size={lot_size}, direction={direction}, price={price}, sl={stop_loss}, tp={take_profit}")

        trade_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot_size,
            "type": order_type,
            "price": price,
            "sl": stop_loss,
            "tp": take_profit,
            "deviation": 10,
            "magic": 0,
            "comment": "Trade placed via API",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        print("🔹 Sending Trade Request...")
        result = mt5.order_send(trade_request)
        print("order_send result:", result)

        if result is None:
            # Retrieve last error if available
            error_code, error_message = mt5.last_error()
            return {"error": f"❌ Trade execution failed: {error_code} - {error_message}"}

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {"error": f"❌ Trade failed: {result.comment}"}

        print("✅ Trade Executed Successfully!")
        return {
            "message": "Trade executed successfully",
            "order_id": result.order,
            "deal_id" : result.deal,
            "volume": lot_size,
            "symbol": symbol,
            "direction": direction.upper(),
            "price": price
            
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




