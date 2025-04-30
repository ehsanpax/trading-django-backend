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
            raise ValueError(rv["error"])

        final_lot = rv["lot_size"]
        sl_price  = rv["stop_loss_price"]
        tp_price  = rv["take_profit_price"]

        # extra guard rails, just like the old view did
        rm = fetch_risk_settings(account.id)
        rc = perform_risk_checks(rm, Decimal(final_lot), self.data["symbol"], Decimal(self.data["risk_percent"]))
        if "error" in rc:
            raise ValueError(rc["error"])

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
                raise RuntimeError(resp["error"])

            # if filled immediately, grab full position info
            if resp.get("status") == "filled":
                pos = conn.get_position_by_ticket(resp["order_id"]) or {}
                resp["position_info"] = pos

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
                raise RuntimeError(resp["error"])
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
            pos = resp.get("position_info", {})
            trade = Trade.objects.create(
                account         = account,
                instrument      = self.data["symbol"],
                direction       = self.data["direction"],
                lot_size        = Decimal(pos.get("volume", final_lot)),
                remaining_size  = Decimal(pos.get("volume", final_lot)),
                entry_price     = Decimal(pos.get("price_open", tp_price)),
                stop_loss       = Decimal(pos.get("sl", sl_price)),
                profit_target   = Decimal(pos.get("tp", tp_price)),
                trade_status    = "open",
                order_id        = resp["order_id"],
                deal_id         = resp.get("deal_id"),
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
