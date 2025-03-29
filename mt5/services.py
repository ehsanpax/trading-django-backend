# mt5/services.py
import MetaTrader5 as mt5

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
            open_positions.append({
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "price_open": pos.price_open,
                "profit": pos.profit,
                "time": pos.time
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
