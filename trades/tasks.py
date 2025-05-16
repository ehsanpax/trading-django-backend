# trades/tasks.py
#from trading_platform.celery_app import shared_task
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from celery import shared_task
from trading.models import ProfitTarget, Trade, Order # Added Order import
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


# Import for MT5 global state management if needed within the task
import MetaTrader5 as mt5_global 
from trades.services import synchronize_trade_with_platform

@shared_task(name="trades.tasks.scan_profit_targets")
def scan_profit_targets():
    """
    Periodically scans for open trades with pending profit targets.
    If a target is hit, it executes a partial closure on the trading platform
    and updates the local database by calling synchronize_trade_with_platform.
    Moves SL to breakeven after TP1 if applicable.
    """
    task_name = "scan_profit_targets"
    print(f"CELERY TASK: {task_name} CALLED at {timezone.now()}")

    pending_targets = ProfitTarget.objects.select_related(
        "trade__account",
        "trade__account__mt5_account",  # Ensures MT5Account is fetched if platform is MT5
        "trade__account__ctrader_account" # Ensures CTraderAccount is fetched if platform is CTrader
    ).filter(status="pending", trade__trade_status="open")

    if not pending_targets.exists():
        print(f"{task_name}: No pending profit targets found for open trades.")
        return f"{task_name}: No pending profit targets."

    processed_targets = 0
    errors_occurred = 0

    # Group targets by account to manage connections efficiently
    targets_by_account = {}
    for pt in pending_targets:
        if pt.trade.account.id not in targets_by_account:
            targets_by_account[pt.trade.account.id] = []
        targets_by_account[pt.trade.account.id].append(pt)

    for account_id, account_targets in targets_by_account.items():
        if not account_targets:
            continue

        # Assume all targets for this account use the same platform
        account_instance = account_targets[0].trade.account
        log_prefix_account = f"{task_name} (Account: {account_instance.id}, Platform: {account_instance.platform}): "
        
        connector = None
        mt5_session_managed_by_this_loop = False

        try:
            print(f"{log_prefix_account}Attempting to get connector.")
            connector = get_connector(account_instance)
            if not connector:
                print(f"{log_prefix_account}Failed to get connector. Skipping targets for this account.")
                errors_occurred += len(account_targets)
                continue
            
            # If MT5, this task initiated the connection via get_connector, so it should manage its shutdown.
            if account_instance.platform == "MT5":
                mt5_session_managed_by_this_loop = True
            
            print(f"{log_prefix_account}Connector obtained. Processing {len(account_targets)} targets.")

            for pt in account_targets:
                trade = pt.trade
                log_prefix_trade = f"{log_prefix_account}TradeID: {trade.id}, PT_ID: {pt.id}, Symbol: {trade.instrument}: "

                if not trade.position_id:
                    print(f"{log_prefix_trade}Skipping - Trade has no position_id.")
                    continue

                print(f"{log_prefix_trade}Fetching live price...")
                price_data = connector.get_live_price(trade.instrument)

                if not price_data or ("bid" not in price_data and "ask" not in price_data): # Check for valid price structure
                    print(f"{log_prefix_trade}Failed to get valid live price. Skipping. Price Data: {price_data}")
                    continue
                
                print(f"{log_prefix_trade}Live price: {price_data}. Target price: {pt.target_price}")

                if hit_target(trade.direction, price_data, pt.target_price):
                    print(f"{log_prefix_trade}Target HIT!")
                    partial_close_success = False
                    platform_actions_attempted = False
                    tp_deal_id = None # To store the deal ID from the TP closure

                    try:
                        # Note: For MT5, connector.close_trade expects 'ticket' to be the position_id.
                        # The MT5Connector.close_trade method uses 'position' parameter with this ticket.
                        print(f"{log_prefix_trade}Attempting to close partial volume: {pt.target_volume} for position {trade.position_id}")
                        platform_actions_attempted = True
                        close_response = connector.close_trade(
                            ticket=trade.position_id, 
                            volume=float(pt.target_volume), 
                            symbol=trade.instrument
                        )

                        if close_response.get("error"):
                            print(f"{log_prefix_trade}Error closing partial volume: {close_response['error']}")
                            errors_occurred +=1
                            continue # Skip this target on error
                        
                        print(f"{log_prefix_trade}Partial volume closed successfully on platform. Response: {close_response}")
                        partial_close_success = True
                        tp_deal_id = close_response.get("deal_id") # Capture the deal_id

                        # If TP1 and SL to Breakeven is configured
                        if pt.rank == 1 and trade.entry_price is not None:
                            print(f"{log_prefix_trade}TP1 hit. Attempting to move SL to breakeven: {trade.entry_price}")
                            if hasattr(connector, "modify_position_protection"):
                                sl_response = connector.modify_position_protection(
                                    position_id=trade.position_id,
                                    symbol=trade.instrument,
                                    stop_loss=float(trade.entry_price)
                                )
                                if sl_response.get("error"):
                                    print(f"{log_prefix_trade}Error moving SL to breakeven: {sl_response['error']}")
                                    # Log error but don't necessarily fail the whole TP hit
                                else:
                                    print(f"{log_prefix_trade}SL moved to breakeven successfully.")
                            else:
                                print(f"{log_prefix_trade}Connector does not support modify_position_protection.")
                        
                        # Mark ProfitTarget as hit in DB after successful platform operation
                        with transaction.atomic():
                            pt_db = ProfitTarget.objects.select_for_update().get(id=pt.id)
                            if pt_db.status == "pending": # Ensure it's still pending
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
                        continue # Skip this target on error

                    if partial_close_success:
                        print(f"{log_prefix_trade}Synchronizing trade with platform after partial close.")
                        try:
                            # synchronize_trade_with_platform handles its own MT5 connection lifecycle
                            sync_result = synchronize_trade_with_platform(trade_id=trade.id)
                            if sync_result.get("error"):
                                print(f"{log_prefix_trade}Error during post-action synchronization: {sync_result['error']}")
                                errors_occurred += 1
                            else:
                                print(f"{log_prefix_trade}Post-action synchronization successful.")
                                processed_targets += 1
                                # Now, update the closure_reason for the specific Order created for this TP deal
                                if tp_deal_id:
                                    try:
                                        order_for_tp_deal = Order.objects.get(broker_deal_id=tp_deal_id, trade=trade)
                                        order_for_tp_deal.closure_reason = f"TP{pt.rank} hit by automated scan"
                                        order_for_tp_deal.save(update_fields=['closure_reason'])
                                        print(f"{log_prefix_trade}Updated closure_reason for Order (DealID: {tp_deal_id}) to 'TP{pt.rank} hit by automated scan'.")
                                    except Order.DoesNotExist:
                                        print(f"{log_prefix_trade}Could not find Order with DealID {tp_deal_id} to update closure_reason.")
                                    except Exception as e_order_update:
                                        print(f"{log_prefix_trade}Exception updating closure_reason for Order (DealID: {tp_deal_id}): {e_order_update}")
                                else:
                                    print(f"{log_prefix_trade}No tp_deal_id captured from close_response, cannot update Order closure_reason.")
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
            errors_occurred += len(account_targets) # Count all targets for this account as errored/skipped
        finally:
            if mt5_session_managed_by_this_loop and mt5_global.terminal_info():
                print(f"{log_prefix_account}Shutting down MT5 connection for account.")
                mt5_global.shutdown()
            elif account_instance.platform == "MT5" and mt5_global.terminal_info():
                 # Fallback if somehow session was started but flag not set (should not happen)
                print(f"{log_prefix_account}MT5 terminal active, attempting shutdown (fallback).")
                mt5_global.shutdown()


    print(f"{task_name} finished. Processed successfully: {processed_targets}, Errors/Skipped: {errors_occurred}.")
    return f"{task_name}: Processed {processed_targets}, Errors/Skipped {errors_occurred}."
