# trades/services.py
from decimal import Decimal
import requests
from django.shortcuts import get_object_or_404
from accounts.models import Account, MT5Account, CTraderAccount
from connectors.ctrader_client import CTraderClient
from mt5.services import MT5Connector # Ensure this is the correct import for your MT5Connector
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


API_BASE_URL = "http://192.168.1.5:8000/api"  # آدرس API MT5
API_KEY = "YOUR_MT5_API_KEY"  # اگر لازم داری

class MT5APIClient:
    def __init__(self, base_url, api_key=None):
        self.base_url = base_url
        self.headers = {}
        if api_key:
            self.headers["Authorization"] = f"Token {api_key}"

    def connect(self, account_number, password, broker_server):
        url = f"{self.base_url}/mt5/connect/"
        payload = {
            "account_number": account_number,
            "password": password,
            "broker_server": broker_server,
        }
        resp = requests.post(url, json=payload, headers=self.headers)
        return resp.json()

    def place_trade(self, data):
        url = f"{self.base_url}/mt5/trade/"
        resp = requests.post(url, json=data, headers=self.headers)
        return resp.json()

    def close_trade(self, data):
        url = f"{self.base_url}/mt5/trade/"
        resp = requests.post(url, json=data, headers=self.headers)
        return resp.json()

    def get_position_by_order_id(self, order_id):
        url = f"{self.base_url}/mt5/position/{order_id}/"
        resp = requests.get(url, headers=self.headers)
        return resp.json()

# ----------------- تابع partial close trade ----------------------

def partially_close_trade(user, trade_id, volume_to_close: Decimal) -> dict:
    trade = get_object_or_404(Trade, id=trade_id)

    if trade.account.user != user:
        raise PermissionDenied("Unauthorized to partially close this trade.")

    if trade.trade_status != "open":
        raise ValidationError("Trade is not open, cannot partially close.")

    if not (Decimal("0.01") <= volume_to_close < trade.remaining_size):
        raise ValidationError(
            f"Volume to close ({volume_to_close}) must be between 0.01 and less than remaining size ({trade.remaining_size}). "
            f"For full closure, use the close trade endpoint."
        )

    if trade.account.platform == "MT5":
        try:
            mt5_account = trade.account.mt5_account
        except MT5Account.DoesNotExist:
            raise APIException("No linked MT5 account found for this trade's account.")

        client = MT5APIClient(API_BASE_URL, api_key=API_KEY)
        login_result = client.connect(mt5_account.account_number, mt5_account.encrypted_password, mt5_account.broker_server)
        if "error" in login_result:
            raise APIException(f"MT5 connection failed: {login_result['error']}")

        if not trade.position_id:
            raise APIException(f"Cannot partially close trade {trade.id}: Missing MT5 position ticket (position_id).")

        close_payload = {
            "account_id": str(trade.account.id),
            "ticket": trade.position_id,
            "volume": float(volume_to_close),
            "symbol": trade.instrument,
            "action": "close",
        }
        close_result = client.close_trade(close_payload)

        if "error" in close_result:
            raise APIException(f"MT5 trade partial closure failed: {close_result['error']}")

        # Sync DB with platform state after partial close
        sync_result = synchronize_trade_with_platform(trade_id=trade.id)

        if "error" in sync_result:
            raise APIException(f"Trade partially closed on platform, but DB sync failed: {sync_result['error']}. Please check trade status.")

        closed_order = Order.objects.filter(trade=trade, status=Order.Status.FILLED).order_by('-filled_at', '-created_at').first()
        profit_on_closed = Decimal("0.0")
        if closed_order and closed_order.volume == volume_to_close:
            profit_on_closed = (closed_order.profit or 0) + (closed_order.commission or 0) + (closed_order.swap or 0)

        trade.refresh_from_db()

        return {
            "message": "Trade partially closed successfully.",
            "trade_id": str(trade.id),
            "closed_volume": float(volume_to_close),
            "remaining_volume": float(trade.remaining_size),
            "profit_on_closed_portion": float(profit_on_closed),
            "current_trade_actual_profit_loss": float(trade.actual_profit_loss or 0),
        }

    elif trade.account.platform == "cTrader":
        raise APIException("cTrader partial close not implemented yet.")
    else:
        raise APIException(f"Unsupported platform: {trade.account.platform}")

# ----------------- کلاس TradeService ----------------------

class TradeService:
    def __init__(self, user, validated_data):
        self.user = user
        self.data = validated_data

    def _get_account(self):
        acct = get_object_or_404(Account, id=self.data["account_id"])
        if acct.user_id != self.user.id:
            raise PermissionDenied("Unauthorized")
        return acct

    def _get_api_client(self, account):
        if account.platform == "MT5":
            mt5_acc = get_object_or_404(MT5Account, account=account)
            client = MT5APIClient(API_BASE_URL, api_key=API_KEY)
            login_result = client.connect(mt5_acc.account_number, mt5_acc.encrypted_password, mt5_acc.broker_server)
            if "error" in login_result:
                raise APIException(f"MT5 connection failed: {login_result['error']}")
            return client

        if account.platform == "cTrader":
            ct_acc = get_object_or_404(CTraderAccount, account=account)
            from connectors.ctrader_client import CTraderClient
            return CTraderClient(ct_acc)

        raise APIException(f"Unsupported platform: {account.platform}")

    def validate(self):
        # گرفتن حساب و بررسی دسترسی
        account = self._get_account()

        # اعتبارسنجی و تبدیل مقادیر ورودی
        try:
            final_lot = Decimal(str(self.data.get("lot")))
        except Exception:
            raise ValidationError("Invalid lot size.")

        if final_lot <= 0:
            raise ValidationError("Lot size must be greater than zero.")

        stop_loss = self.data.get("stop_loss")
        take_profit = self.data.get("take_profit")
        order_type = self.data.get("order_type")
        risk_percent = self.data.get("risk_percent")
        projected_profit = self.data.get("projected_profit")
        projected_loss = self.data.get("projected_loss")
        rr_ratio = self.data.get("rr_ratio")

        required_fields = {
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "order_type": order_type,
            "risk_percent": risk_percent,
            "projected_profit": projected_profit,
            "projected_loss": projected_loss,
            "rr_ratio": rr_ratio,
        }
        missing_fields = [k for k,v in required_fields.items() if v is None]
        if missing_fields:
            raise ValidationError(f"Missing required fields: {', '.join(missing_fields)}")

        # تبدیل مقادیر به Decimal (اگر لازم بود)
        try:
            sl_price = Decimal(str(stop_loss))
            tp_price = Decimal(str(take_profit))
            risk_percent = Decimal(str(risk_percent))
            projected_profit = Decimal(str(projected_profit))
            projected_loss = Decimal(str(projected_loss))
            rr_ratio = Decimal(str(rr_ratio))
        except Exception:
            raise ValidationError("Invalid decimal values in one of the fields.")

        # اعتبارسنجی order_type بر اساس انتخاب‌های مجاز
        allowed_order_types = ["LIMIT", "STOP", "MARKET"]  # فرض کن این‌ها مقادیر معتبرند؛ جایگزین با مقادیر واقعی پروژه‌ات کن
        if order_type.upper() not in allowed_order_types:
            raise ValidationError(f"Invalid order_type. Must be one of: {', '.join(allowed_order_types)}")

        return account, final_lot, sl_price, tp_price

    def execute_on_broker(self, account, final_lot, sl_price, tp_price):
        client = self._get_api_client(account)

        if account.platform == "MT5":
            payload = {
                "account_id": str(account.id),
                "symbol": self.data["symbol"],
                "lot_size": float(final_lot),
                "direction": self.data["direction"],
                "order_type": self.data["order_type"],
                "limit_price": self.data.get("limit_price"),
                "time_in_force": self.data.get("time_in_force", "GTC"),
                "stop_loss": float(sl_price),
                "take_profit": float(tp_price),
            }
            resp = client.place_trade(payload)
            if "error" in resp:
                raise APIException(resp["error"])

            if resp.get("status") == "filled":
                opened_ticket = resp.get("opened_position_ticket")
                if opened_ticket:
                    pos_details = client.get_position_by_order_id(opened_ticket)
                    if "error" in pos_details:
                        pos_details = client.get_position_by_order_id(resp.get("order_id")) or {}
                    resp["position_info"] = pos_details
                else:
                    pos_details = client.get_position_by_order_id(resp.get("order_id")) or {}
                    resp["position_info"] = pos_details

        else:  # cTrader
            resp = client.place_order(
                symbol=self.data["symbol"],
                volume=float(final_lot),
                trade_side=self.data["direction"],
                order_type=self.data["order_type"],
                limit_price=self.data.get("limit_price"),
                time_in_force=self.data.get("time_in_force", "GTC"),
                stop_loss=float(sl_price),
                take_profit=float(tp_price),
            )
            if "error" in resp:
                raise APIException(resp["error"])

        return resp

    def persist(self, account, resp, final_lot, sl_price, tp_price):
        # snapshot از شاخص‌ها (باید تو پروژه تعریف شده باشه)
        snapshot = {
            "RSI_M1": get_cached(self.data["symbol"], "M1", "RSI"),
            "ATR_M1": get_cached(self.data["symbol"], "M1", "ATR"),
        }

        order = Order.objects.create(
            id=uuid4(),
            account=account,
            instrument=self.data["symbol"],
            direction=self.data["direction"],
            order_type=self.data["order_type"],
            volume=final_lot,
            price=(Decimal(self.data["limit_price"]) if self.data.get("limit_price") is not None else None),
            stop_loss=sl_price,
            take_profit=tp_price,
            time_in_force=self.data.get("time_in_force", "GTC"),
            broker_order_id=resp["order_id"],
            status=resp.get("status", "pending"),
        )

        trade = None
        if resp.get("status") == "filled":
            raw_position_info = resp.get("position_info", {})

            trade_lot_size = final_lot
            trade_entry_price = resp.get("price")
            trade_sl = sl_price
            trade_tp = tp_price

            if raw_position_info and not raw_position_info.get("error"):
                trade_lot_size = raw_position_info.get("volume", final_lot)
                if raw_position_info.get("price_open") is not None:
                    trade_entry_price = raw_position_info.get("price_open")
                trade_sl = raw_position_info.get("sl", sl_price)
                trade_tp = raw_position_info.get("tp", tp_price)
            elif raw_position_info.get("error"):
                print(f"Warning: position_info error: {raw_position_info.get('error')}")

            db_trade_position_id = None
            if account.platform == "MT5" and self.data.get("order_type", "").upper() == "MARKET":
                db_trade_position_id = resp.get("order_id")
            elif raw_position_info and not raw_position_info.get("error"):
                db_trade_position_id = raw_position_info.get("ticket")

            if db_trade_position_id is None:
                print(f"Warning: Trade.position_id NULL for order {resp.get('order_id')}.")

            trade = Trade.objects.create(
                account=account,
                instrument=self.data["symbol"],
                direction=self.data["direction"],
                lot_size=trade_lot_size,
                remaining_size=trade_lot_size,
                entry_price=trade_entry_price if trade_entry_price is not None else None,
                stop_loss=trade_sl,
                profit_target=trade_tp,
                trade_status="open",
                order_id=resp["order_id"],
                deal_id=resp.get("deal_id"),
                position_id=db_trade_position_id,
                risk_percent=Decimal(self.data["risk_percent"]),
                projected_profit=Decimal(self.data["projected_profit"]),
                projected_loss=Decimal(self.data["projected_loss"]),
                rr_ratio=Decimal(self.data["rr_ratio"]),
                reason=self.data.get("reason", ""),
                indicators=snapshot,
            )
            order.trade = trade
            order.save(update_fields=["trade"])

        # اگر partial_profit تعریف شده باشه، اهداف جزئی ایجاد کن
        if self.data.get("partial_profit") and trade:
            total = Decimal(final_lot)
            for leg in sorted(self.data["targets"], key=lambda x: x["rank"]):
                cfg = {
                    **leg,
                    "stop_loss_price": trade.stop_loss,
                    "symbol": trade.instrument,
                }
                price = derive_target_price(trade.entry_price, cfg, trade.direction)
                vol = (total * Decimal(str(leg["share"]))).quantize(Decimal("0.01"))
                ProfitTarget.objects.create(
                    trade=trade,
                    rank=leg["rank"],
                    target_price=price,
                    target_volume=vol,
                )

        return order, trade

    def build_response(self, order, trade):
        out = {
            "message": "Order accepted",
            "order_id": order.broker_order_id,
            "order_status": order.status,
        }
        if trade:
            out.update({
                "trade_id": str(trade.id),
                "entry_price": float(trade.entry_price),
            })
        return out


def close_trade_globally(user, trade_id: UUID) -> dict:
    trade = get_object_or_404(Trade, id=trade_id)

    if trade.account.user != user:
        raise PermissionDenied("Unauthorized to close this trade")

    if trade.trade_status != "open":
        raise ValidationError("Trade is already closed")

    profit = None

    if trade.account.platform == "MT5":
        try:
            mt5_account = trade.account.mt5_account
        except MT5Account.DoesNotExist:
            raise APIException("No linked MT5 account found for this trade's account.")

        client = MT5APIClient(API_BASE_URL, api_key=API_KEY)
        login_result = client.connect(mt5_account.account_number, mt5_account.encrypted_password, mt5_account.broker_server)
        if "error" in login_result:
            raise APIException(f"MT5 connection failed: {login_result['error']}")

        position_ticket = trade.position_id or trade.order_id
        if not position_ticket:
            raise APIException(f"Cannot close trade {trade.id}: Missing MT5 position ticket (position_id or order_id).")

        close_payload = {
            "account_id": str(trade.account.id),
            "ticket": position_ticket,
            "volume": float(trade.remaining_size),
            "symbol": trade.instrument,
            "action": "close",
        }
        close_result = client.close_trade(close_payload)

        if "error" in close_result:
            raise APIException(f"MT5 trade closure failed: {close_result['error']}")

        final_details = client.get_closing_deal_details_for_position(position_ticket)
        if "error" in final_details:
            print(f"Warning: Trade {trade.id} closed on platform but failed to fetch final P/L: {final_details['error']}")
            profit = Decimal(0)
        else:
            profit = (
                Decimal(str(final_details.get("profit", 0))) +
                Decimal(str(final_details.get("commission", 0))) +
                Decimal(str(final_details.get("swap", 0)))
            )
            trade.commission = Decimal(str(final_details.get("commission", trade.commission or 0)))
            trade.swap = Decimal(str(final_details.get("swap", trade.swap or 0)))

    elif trade.account.platform == "cTrader":
        raise APIException("cTrader close not implemented yet.")
    else:
        raise APIException("Unsupported trading platform.")

    trade.trade_status = "closed"
    trade.closed_at = django_timezone.now()
    if profit is not None:
        trade.actual_profit_loss = profit
    trade.save()

    return {
        "message": "Trade closed successfully",
        "trade_id": str(trade.id),
        "actual_profit_loss": float(trade.actual_profit_loss or 0)
    }

# ----------- تابع synchronize_trade_with_platform با استفاده از API Client ----------

def synchronize_trade_with_platform(trade_id: UUID, existing_client: MT5APIClient = None) -> dict:
    try:
        trade = get_object_or_404(Trade, id=trade_id)
    except Trade.DoesNotExist:
        return {"error": f"Trade with id {trade_id} not found."}

    client = existing_client
    platform = trade.account.platform

    if platform == "MT5":
        if not client:
            try:
                mt5_acc = MT5Account.objects.get(account=trade.account)
            except MT5Account.DoesNotExist:
                return {"error": f"MT5Account details not found for account {trade.account.id}."}

            client = MT5APIClient(API_BASE_URL, api_key=API_KEY)
            connect_res = client.connect(mt5_acc.account_number, mt5_acc.encrypted_password, mt5_acc.broker_server)
            if "error" in connect_res:
                return {"error": f"MT5 connection failed: {connect_res['error']}"}

        if not trade.position_id:
            return {"error": f"Trade {trade.id} has no position_id, cannot sync."}

        sync_data = client.fetch_trade_sync_data(trade.position_id, trade.instrument)

    elif platform == "cTrader":
        return {"error": "cTrader synchronization not yet implemented."}
    else:
        return {"error": f"Unsupported platform: {platform}"}

    if not sync_data:
        return {"error": "Failed to retrieve sync data from platform."}

    if sync_data.get("error_message"):
        return {"error": f"Platform error: {sync_data.get('error_message')}"}

    existing_deal_ids = set(
        trade.order_history.values_list('broker_deal_id', flat=True).exclude(broker_deal_id__isnull=True)
    )

    for deal in sync_data.get("deals", []):
        deal_ticket = deal.get("ticket")
        if deal_ticket and deal_ticket not in existing_deal_ids:
            Order.objects.create(
                account=trade.account,
                instrument=deal.get("symbol"),
                direction=Order.Direction.BUY if deal.get("type") == 0 else Order.Direction.SELL,
                order_type=Order.OrderType.MARKET,
                volume=deal.get("volume"),
                price=deal.get("price"),
                status=Order.Status.FILLED,
                broker_order_id=deal.get("order"),
                broker_deal_id=deal_ticket,
                filled_price=deal.get("price"),
                filled_volume=deal.get("volume"),
                filled_at=datetime.fromtimestamp(deal.get("time"), tz=dt_timezone.utc) if deal.get("time") else None,
                profit=deal.get("profit"),
                commission=deal.get("commission"),
                swap=deal.get("swap"),
                broker_deal_reason_code=deal.get("reason"),
                trade=trade,
            )
            existing_deal_ids.add(deal_ticket)

    trade.remaining_size = sync_data.get("platform_remaining_size", trade.remaining_size)

    if sync_data.get("is_closed_on_platform") and trade.trade_status == "open":
        trade.trade_status = "closed"
        latest_ts = sync_data.get("latest_deal_timestamp")
        if latest_ts:
            trade.closed_at = datetime.fromtimestamp(latest_ts, tz=dt_timezone.utc)
        else:
            trade.closed_at = django_timezone.now()

        profit = sync_data.get("final_profit", Decimal("0")) or Decimal("0")
        commission = sync_data.get("final_commission", Decimal("0")) or Decimal("0")
        swap = sync_data.get("final_swap", Decimal("0")) or Decimal("0")
        trade.actual_profit_loss = profit + commission + swap

    try:
        trade.save()
        return {
            "message": f"Trade {trade.id} synchronized successfully.",
            "trade_id": str(trade.id),
            "status": trade.trade_status,
            "remaining_size": str(trade.remaining_size),
        }
    except Exception as e:
        return {"error": f"Failed to save trade {trade.id}: {str(e)}"}

# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
#                  UPDATE TRADE STOP LOSS / TAKE PROFIT
# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
def update_trade_protection_levels(user, 
                                   trade_id: UUID, 
                                   new_stop_loss: Decimal = None, 
                                   new_take_profit: Decimal = None) -> dict:
    """
    فقط برای بروزرسانی Take Profit استفاده می‌شود.
    اگر new_stop_loss داده شود، خطا می‌دهد و باید از endpoint جداگانه SL استفاده شود.
    """
    trade = get_object_or_404(Trade, id=trade_id)

    if trade.account.user != user:
        raise PermissionDenied("Unauthorized to update this trade's protection levels.")

    if trade.trade_status != "open":
        raise ValidationError("Protection levels can only be updated for open trades.")

    if new_take_profit is None:
        raise ValidationError("new_take_profit must be provided.")

    if new_stop_loss is not None:
        raise ValidationError("This endpoint is only for updating take profit. Use the SL update endpoint for stop loss.")

    account = trade.account

    if account.platform == "MT5":
        try:
            mt5_account = account.mt5_account
        except MT5Account.DoesNotExist:
            raise APIException("No linked MT5 account found for this trade's account.")

        client = MT5APIClient(API_BASE_URL, api_key=API_KEY)
        login_res = client.connect(mt5_account.account_number, mt5_account.encrypted_password, mt5_account.broker_server)
        if "error" in login_res:
            raise APIException(f"MT5 connection failed: {login_res['error']}")

        if not trade.position_id:
            raise APIException(f"Trade {trade.id} does not have a position_id. Cannot update protection on MT5.")

        # گرفتن SL فعلی از پوزیشن زنده روی پلتفرم
        pos_details = client.get_open_position_details_by_ticket(position_ticket=int(trade.position_id))
        if "error" in pos_details:
            raise APIException(f"Failed to fetch current position details from MT5: {pos_details['error']}")

        current_sl = float(Decimal(str(pos_details.get("sl", 0.0))))

        # ارسال درخواست تغییر TP همراه با SL فعلی
        response = client.modify_position_protection(
            position_id=int(trade.position_id),
            symbol=trade.instrument,
            stop_loss=current_sl,
            take_profit=float(new_take_profit)
        )
        if "error" in response:
            raise APIException(f"MT5 take profit update failed: {response['error']}")

        # ذخیره در دیتابیس
        trade.profit_target = new_take_profit
        trade.save(update_fields=["profit_target"])

        return {
            "message": "Trade take profit updated successfully.",
            "trade_id": str(trade.id),
            "new_take_profit": float(trade.profit_target),
            "platform_response": response
        }

    elif account.platform == "cTrader":
        raise APIException("cTrader take profit update not implemented yet.")
    else:
        raise APIException(f"Unsupported platform: {account.platform}")


def update_trade_stop_loss_globally(user,
                                    trade_id: UUID,
                                    sl_update_type: str, # "breakeven", "distance_pips", "distance_price", "specific_price"
                                    value: Decimal = None, 
                                    specific_price: Decimal = None) -> dict:
    """
    به‌روزرسانی Stop Loss بر اساس نوع درخواست.
    """
    trade = get_object_or_404(Trade, id=trade_id)

    if trade.account.user != user:
        raise PermissionDenied("Unauthorized to update this trade's stop loss.")

    if trade.trade_status != "open":
        raise ValidationError("Stop loss can only be updated for open trades.")

    account = trade.account

    if account.platform == "MT5":
        try:
            mt5_account = account.mt5_account
        except MT5Account.DoesNotExist:
            raise APIException("No linked MT5 account found for this trade's account.")

        client = MT5APIClient(API_BASE_URL, api_key=API_KEY)
        login_res = client.connect(mt5_account.account_number, mt5_account.encrypted_password, mt5_account.broker_server)
        if "error" in login_res:
            raise APIException(f"MT5 connection failed: {login_res['error']}")

        if not trade.position_id:
            raise APIException(f"Trade {trade.id} does not have a position_id. Cannot update SL on MT5.")

        pos_details = client.get_open_position_details_by_ticket(position_ticket=int(trade.position_id))
        if "error" in pos_details:
            raise APIException(f"Failed to fetch current position details from MT5: {pos_details['error']}")

        current_tp = Decimal(str(pos_details.get("tp", 0.0)))

        # محاسبه قیمت جدید SL
        new_sl_price = None

        if sl_update_type == "breakeven":
            if trade.entry_price is None:
                raise ValidationError("Cannot set SL to breakeven as entry price is not available.")
            new_sl_price = trade.entry_price

        elif sl_update_type == "specific_price":
            if specific_price is None:
                raise ValidationError("specific_price must be provided for 'specific_price' update type.")
            new_sl_price = specific_price

        elif sl_update_type in ["distance_pips", "distance_price"]:
            if value is None:
                raise ValidationError(f"A 'value' must be provided for '{sl_update_type}'.")

            live_price_data = client.get_live_price(symbol=trade.instrument)
            if "error" in live_price_data:
                raise APIException(f"Could not fetch live price for {trade.instrument}: {live_price_data['error']}")

            if trade.direction == "BUY":
                current_market_price = Decimal(str(live_price_data["bid"]))
            elif trade.direction == "SELL":
                current_market_price = Decimal(str(live_price_data["ask"]))
            else:
                raise ValidationError(f"Invalid trade direction: {trade.direction}")

            offset = Decimal(str(value))

            if sl_update_type == "distance_pips":
                symbol_info = client.get_symbol_info(symbol=trade.instrument)
                if "error" in symbol_info:
                    raise APIException(f"Could not fetch symbol info for {trade.instrument}: {symbol_info['error']}")
                pip_size = Decimal(str(symbol_info["pip_size"]))
                offset = offset * pip_size

            if trade.direction == "BUY":
                new_sl_price = current_market_price - offset
            else:
                new_sl_price = current_market_price + offset

            # گرد کردن قیمت به تعداد ارقام اعشار مناسب
            symbol_info_round = client.get_symbol_info(symbol=trade.instrument)
            if "error" in symbol_info_round:
                raise APIException(f"Could not fetch symbol info for rounding: {symbol_info_round['error']}")

            tick_size_str = str(symbol_info_round.get("tick_size", "0.00001"))
            if '.' in tick_size_str:
                digits = len(tick_size_str.split('.')[1])
            else:
                digits = 0

            new_sl_price = new_sl_price.quantize(Decimal(f'1e-{digits}'))

        else:
            raise ValidationError(f"Invalid sl_update_type: {sl_update_type}")

        if new_sl_price is None:
            raise APIException("Failed to calculate new stop loss price.")

        # قوانین SL
        if sl_update_type == "specific_price" and new_sl_price == Decimal("0.0"):
            raise ValidationError("Stop loss removal (setting to 0.0) not allowed via this endpoint.")

        if trade.stop_loss not in [None, Decimal("0.0")]:
            current_db_sl = trade.stop_loss
            if trade.direction == "BUY" and new_sl_price < current_db_sl:
                raise ValidationError(f"New stop loss ({new_sl_price}) cannot be further (lower) than current SL ({current_db_sl}) for BUY.")
            if trade.direction == "SELL" and new_sl_price > current_db_sl:
                raise ValidationError(f"New stop loss ({new_sl_price}) cannot be further (higher) than current SL ({current_db_sl}) for SELL.")

        # ارسال درخواست تغییر SL به پلتفرم
        modification_res = client.modify_position_protection(
            position_id=int(trade.position_id),
            symbol=trade.instrument,
            stop_loss=float(new_sl_price),
            take_profit=float(current_tp)
        )
        if "error" in modification_res:
            raise APIException(f"MT5 stop loss update failed: {modification_res['error']}")

        trade.stop_loss = new_sl_price
        trade.save(update_fields=["stop_loss"])

        return {
            "message": "Stop loss updated successfully.",
            "trade_id": str(trade.id),
            "new_stop_loss": float(new_sl_price),
            "platform_response": modification_res
        }

    elif account.platform == "cTrader":
        raise APIException("cTrader stop loss update not implemented yet.")
    else:
        raise APIException(f"Unsupported platform: {account.platform}")