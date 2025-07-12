import requests
from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from celery import shared_task
from trades.models import ProfitTarget, Trade, Order
from accounts.models import Account, MT5Account, CTraderAccount
from trades.services import synchronize_trade_with_platform

API_BASE_URL = "http://192.168.1.5:8000/api" 

def get_live_price_api(account_id, symbol):
    
    try:
        url = f"{API_BASE_URL}/mt5/market-price/{symbol}/{account_id}/"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
       
        return data
    except Exception as e:
        print(f"Error fetching live price for account {account_id}, symbol {symbol}: {e}")
        return None

def close_trade_api(account_id, ticket, volume, symbol):

    try:
        url = f"{API_BASE_URL}/mt5/trade/"
        payload = {
            "account_id": account_id,
            "ticket": ticket,
            "volume": volume,
            "symbol": symbol,
            "action": "close"  
        }
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Error closing trade for account {account_id}, ticket {ticket}: {e}")
        return {"error": str(e)}

def hit_target(direction: str, price: dict, target_price: Decimal) -> bool:
  
    direction = direction.upper()
    if direction == "BUY":
        bid = Decimal(str(price.get("bid", 0)))
        return bid >= target_price
    if direction == "SELL":
        ask = Decimal(str(price.get("ask", 0)))
        return ask <= target_price
    return False

@shared_task(name="trades.tasks.scan_profit_targets")
def scan_profit_targets():
    task_name = "scan_profit_targets"
    print(f"CELERY TASK: {task_name} CALLED at {timezone.now()}")

    pending_targets = ProfitTarget.objects.select_related(
        "trade__account",
        "trade__account__mt5_account",
        "trade__account__ctrader_account"
    ).filter(status="pending", trade__trade_status="open")

    if not pending_targets.exists():
        print(f"{task_name}: No pending profit targets found for open trades.")
        return f"{task_name}: No pending profit targets."

    processed_targets = 0
    errors_occurred = 0

  
    targets_by_account = {}
    for pt in pending_targets:
        acc_id = pt.trade.account.id
        targets_by_account.setdefault(acc_id, []).append(pt)

    for account_id, account_targets in targets_by_account.items():
        if not account_targets:
            continue

        account_instance = account_targets[0].trade.account
        log_prefix_account = f"{task_name} (Account: {account_instance.id}, Platform: {account_instance.platform}): "

        connector = None
        use_api = False

        try:
           
            if account_instance.platform == "MT5":
                use_api = True
                print(f"{log_prefix_account}Using API for MT5 operations.")

            elif account_instance.platform == "cTrader":
                from connectors.ctrader_client import CTraderClient
                ct_acc = CTraderAccount.objects.get(account=account_instance)
                connector = CTraderClient(ct_acc)
                print(f"{log_prefix_account}Using cTrader client connector.")

            else:
                print(f"{log_prefix_account}Unsupported platform. Skipping.")
                errors_occurred += len(account_targets)
                continue

            for pt in account_targets:
                trade = pt.trade
                log_prefix_trade = f"{log_prefix_account}TradeID: {trade.id}, PT_ID: {pt.id}, Symbol: {trade.instrument}: "

                if not trade.position_id:
                    print(f"{log_prefix_trade}Skipping - Trade has no position_id.")
                    continue

                print(f"{log_prefix_trade}Fetching live price...")

                if use_api:
                    price_data = get_live_price_api(str(account_instance.id), trade.instrument)
                else:
                    price_data = connector.get_live_price(trade.instrument)

                if not price_data or ("bid" not in price_data and "ask" not in price_data):
                    print(f"{log_prefix_trade}Failed to get valid live price. Skipping. Price Data: {price_data}")
                    continue

                print(f"{log_prefix_trade}Live price: {price_data}. Target price: {pt.target_price}")

                if hit_target(trade.direction, price_data, pt.target_price):
                    print(f"{log_prefix_trade}Target HIT!")
                    partial_close_success = False
                    tp_deal_id = None

                    try:
                        if use_api:
                            print(f"{log_prefix_trade}Attempting to close partial volume via API: {pt.target_volume} for position {trade.position_id}")
                            close_response = close_trade_api(
                                account_id=str(account_instance.id),
                                ticket=trade.position_id,
                                volume=float(pt.target_volume),
                                symbol=trade.instrument
                            )
                        else:
                            print(f"{log_prefix_trade}Attempting to close partial volume via connector: {pt.target_volume} for position {trade.position_id}")
                            close_response = connector.close_trade(
                                ticket=trade.position_id,
                                volume=float(pt.target_volume),
                                symbol=trade.instrument
                            )

                        if close_response.get("error"):
                            print(f"{log_prefix_trade}Error closing partial volume: {close_response['error']}")
                            errors_occurred += 1
                            continue

                        print(f"{log_prefix_trade}Partial volume closed successfully on platform. Response: {close_response}")
                        partial_close_success = True
                        tp_deal_id = close_response.get("deal_id")

                     
                        if pt.rank == 1 and trade.entry_price is not None:
                            if not use_api and hasattr(connector, "modify_position_protection"):
                                print(f"{log_prefix_trade}TP1 hit. Moving SL to breakeven: {trade.entry_price}")
                                sl_response = connector.modify_position_protection(
                                    position_id=trade.position_id,
                                    symbol=trade.instrument,
                                    stop_loss=float(trade.entry_price)
                                )
                                if sl_response.get("error"):
                                    print(f"{log_prefix_trade}Error moving SL to breakeven: {sl_response['error']}")
                                else:
                                    print(f"{log_prefix_trade}SL moved to breakeven successfully.")
                            else:
                                print(f"{log_prefix_trade}Skipping SL to breakeven move for API or unsupported connector.")

                        with transaction.atomic():
                            pt_db = ProfitTarget.objects.select_for_update().get(id=pt.id)
                            if pt_db.status == "pending":
                                pt_db.status = "hit"
                                pt_db.hit_at = timezone.now()
                                pt_db.save(update_fields=["status", "hit_at"])
                                print(f"{log_prefix_trade}Marked ProfitTarget as HIT in DB.")
                            else:
                                print(f"{log_prefix_trade}ProfitTarget status was not pending ({pt_db.status}). Not updated.")

                    except Exception as e_platform:
                        print(f"{log_prefix_trade}Exception during platform operation: {e_platform}")
                        import traceback
                        traceback.print_exc()
                        errors_occurred += 1
                        continue

                    if partial_close_success:
                        print(f"{log_prefix_trade}Synchronizing trade with platform after partial close.")
                        try:
                            sync_result = synchronize_trade_with_platform(trade_id=trade.id)
                            if sync_result.get("error"):
                                print(f"{log_prefix_trade}Error during post-action synchronization: {sync_result['error']}")
                                errors_occurred += 1
                            else:
                                print(f"{log_prefix_trade}Post-action synchronization successful.")
                                processed_targets += 1

                                if tp_deal_id:
                                    try:
                                        order_for_tp_deal = Order.objects.get(broker_deal_id=tp_deal_id, trade=trade)
                                        order_for_tp_deal.closure_reason = f"TP{pt.rank} hit by automated scan"
                                        order_for_tp_deal.save(update_fields=['closure_reason'])
                                        print(f"{log_prefix_trade}Updated closure_reason for Order (DealID: {tp_deal_id}).")
                                    except Order.DoesNotExist:
                                        print(f"{log_prefix_trade}Could not find Order with DealID {tp_deal_id} to update closure_reason.")
                                    except Exception as e_order_update:
                                        print(f"{log_prefix_trade}Exception updating closure_reason for Order: {e_order_update}")
                                else:
                                    print(f"{log_prefix_trade}No tp_deal_id captured, cannot update Order closure_reason.")
                        except Exception as e_sync:
                            print(f"{log_prefix_trade}Exception during post-action synchronization: {e_sync}")
                            import traceback
                            traceback.print_exc()
                            errors_occurred += 1
                else:
                    print(f"{log_prefix_trade}Target not yet hit.")

        except Exception as e_account_loop:
            print(f"{log_prefix_account}Exception processing account: {e_account_loop}")
            import traceback
            traceback.print_exc()
            errors_occurred += len(account_targets)

    print(f"{task_name} finished. Processed successfully: {processed_targets}, Errors/Skipped: {errors_occurred}.")
    return f"{task_name}: Processed {processed_targets}, Errors/Skipped {errors_occurred}."
