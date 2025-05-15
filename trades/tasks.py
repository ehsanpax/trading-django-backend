# trades/tasks.py
#from trading_platform.celery_app import shared_task
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from celery import shared_task
from trading.models import ProfitTarget, Trade
from accounts.models import Account, MT5Account, CTraderAccount
from mt5.services import MT5Connector
from connectors.ctrader_client import CTraderClient


def get_connector(account: Account):
    """
    Return an authenticated connector for the given account.
    """
    if account.platform == "MT5":
        mt5_acc = MT5Account.objects.get(account=account)
        conn = MT5Connector(mt5_acc.account_number, mt5_acc.broker_server)
        conn.connect(mt5_acc.encrypted_password)
        return conn

    if account.platform == "cTrader":
        ct_acc = CTraderAccount.objects.get(account=account)
        return CTraderClient(ct_acc)

    raise ValueError(f"Unsupported platform: {account.platform}")


def hit_target(direction: str, price: dict, target_price: Decimal) -> bool:
    """
    Returns True if the live price has met or exceeded the target.
      • BUY  → bid ≥ target_price
      • SELL → ask ≤ target_price
    """
    direction = direction.upper()
    if direction == "BUY":
        bid = Decimal(str(price.get("bid", 0)))
        return bid >= target_price
    if direction == "SELL":
        ask = Decimal(str(price.get("ask", 0)))
        return ask <= target_price
    return False


@shared_task
def scan_profit_targets():
    """
    Temporarily disabled for debugging other Celery issues.
    Periodically close partial volumes when price hits each ProfitTarget,
    update remaining_size and move SL to breakeven after TP1.
    """
    print(f"CELERY TASK: trades.tasks.scan_profit_targets CALLED at {timezone.now()} - Currently disabled for debugging.")
    return "scan_profit_targets is temporarily disabled."
    # Original logic commented out below:
    # # 1️⃣ load all pending legs for open trades
    # pending = ProfitTarget.objects.select_related("trade__account") \
    #     .filter(status="pending", trade__trade_status="open")

    # for pt in pending:
    #     trade   = pt.trade
    #     account = trade.account

    #     # 2️⃣ build the right connector
    #     try:
    #         conn = get_connector(account)
    #     except Exception:
    #         continue  # skip if connector fails

    #     # 3️⃣ fetch live price
    #     price_data = conn.get_live_price(trade.instrument)
    #     if not price_data or "bid" not in price_data:
    #         continue

    #     # 4️⃣ if target hit, do atomic update + broker call
    #     if hit_target(trade.direction, price_data, pt.target_price):
    #         with transaction.atomic():
    #             # — close partial volume
    #             conn.close_trade(
    #                 ticket=trade.order_id,
    #                 volume=float(pt.target_volume),
    #                 symbol=trade.instrument
    #             )

    #             # — update the Trade.remaining_size
    #             trade.remaining_size -= pt.target_volume
    #             trade.save(update_fields=["remaining_size"])

    #             # — mark this leg as hit
    #             pt.status = "hit"
    #             pt.hit_at = timezone.now()
    #             pt.save(update_fields=["status", "hit_at"])

    #             # — after TP1, move SL to breakeven
    #             if pt.rank == 1:
    #                 conn.modify_sl(
    #                     ticket=trade.order_id,
    #                     new_sl=float(trade.entry_price)
    #                 )
