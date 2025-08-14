# trades/tasks.py
#from trading_platform.celery_app import shared_task
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from celery import shared_task
from trading.models import ProfitTarget, Trade, Order # Added Order import
from accounts.models import Account, MT5Account, CTraderAccount
from trading_platform.mt5_api_client import MT5APIClient
from django.conf import settings
from connectors.ctrader_client import CTraderClient


def get_connector(account: Account):
    """
    Return an authenticated connector for the given account.
    """
    if account.platform == "MT5":
        mt5_acc = MT5Account.objects.get(account=account)
        return MT5APIClient(
            base_url=settings.MT5_API_BASE_URL,
            account_id=mt5_acc.account_number,
            password=mt5_acc.encrypted_password,
            broker_server=mt5_acc.broker_server
        )

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
            # No explicit shutdown needed for MT5APIClient as it's stateless HTTP
            pass


    print(f"{task_name} finished. Processed successfully: {processed_targets}, Errors/Skipped: {errors_occurred}.")
    return f"{task_name}: Processed {processed_targets}, Errors/Skipped {errors_occurred}."


@shared_task(name="trades.tasks.trigger_trade_synchronization")
def trigger_trade_synchronization(trade_id: str):
    """
    A Celery task to trigger the synchronization of a single trade.
    """
    print(f"CELERY TASK: Triggering synchronization for trade_id: {trade_id}")
    result = synchronize_trade_with_platform(trade_id=trade_id)
    if result.get("error"):
        print(f"ERROR during synchronization for trade {trade_id}: {result['error']}")
    else:
        print(f"SUCCESS: Synchronization task completed for trade {trade_id}.")
    return result


@shared_task(name="trades.tasks.diagnostic_task")
def diagnostic_task(message: str):
    """
    A simple task to diagnose Celery communication issues.
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"DIAGNOSTIC TASK RECEIVED: {message}")


@shared_task(name="trades.tasks.reconcile_open_positions")
def reconcile_open_positions():
    """
    Periodically checks for discrepancies between open trades in the local database
    and the actual open positions on the MT5 platform. If a trade is marked as 'open'
    locally but is no longer open on MT5, it triggers a synchronization to update
    the local state.
    """
    task_name = "reconcile_open_positions"
    print(f"CELERY TASK: {task_name} CALLED at {timezone.now()}")

    active_mt5_accounts = MT5Account.objects.filter(account__is_active=True)
    
    if not active_mt5_accounts.exists():
        print(f"{task_name}: No active MT5 accounts found.")
        return f"{task_name}: No active MT5 accounts."

    total_synced = 0
    total_errors = 0

    for mt5_account in active_mt5_accounts:
        account = mt5_account.account
        log_prefix = f"{task_name} (Account: {account.id}, MT5 Login: {mt5_account.account_number}): "

        # 1. Query for open trades in the local database first to avoid unnecessary API calls
        local_open_trades = Trade.objects.filter(account=account, trade_status="open")

        if not local_open_trades.exists():
            print(f"{log_prefix}No open trades found in the database. Skipping.")
            continue

        print(f"{log_prefix}Found {local_open_trades.count()} open trade(s) in DB. Checking against platform.")

        try:
            # 2. If local open trades exist, then connect and fetch platform positions
            connector = MT5APIClient(
                base_url=settings.MT5_API_BASE_URL,
                account_id=mt5_account.account_number,
                password=mt5_account.encrypted_password,
                broker_server=mt5_account.broker_server,
                internal_account_id=str(account.id)
            )

            platform_positions_response = connector.get_all_open_positions_rest()
            if "error" in platform_positions_response:
                print(f"{log_prefix}Error fetching open positions from platform: {platform_positions_response['error']}")
                total_errors += 1
                continue

            platform_open_positions = platform_positions_response.get("open_positions", [])
            platform_position_ids = {str(pos['ticket']) for pos in platform_open_positions if 'ticket' in pos and pos.get('type') != 'pending_order'}
            print(f"{log_prefix}Found {len(platform_position_ids)} open position(s) on platform.")

            # 3. Compare and find discrepancies

            # Check for closed trades
            local_position_ids = {str(trade.position_id) for trade in local_open_trades if trade.position_id}
            closed_on_platform = local_position_ids - platform_position_ids
            for position_id in closed_on_platform:
                trade_to_sync = local_open_trades.get(position_id=position_id)
                print(f"{log_prefix}Discrepancy found! Trade {trade_to_sync.id} (PositionID: {position_id}) is 'open' locally but not on the platform. Triggering sync.")
                try:
                    sync_result = synchronize_trade_with_platform(trade_id=trade_to_sync.id)
                    if sync_result.get("error"):
                        print(f"{log_prefix}Error synchronizing trade {trade_to_sync.id}: {sync_result['error']}")
                        total_errors += 1
                    else:
                        print(f"{log_prefix}Successfully synchronized trade {trade_to_sync.id}.")
                        total_synced += 1
                except Exception as e_sync:
                    print(f"{log_prefix}Exception during synchronization for trade {trade_to_sync.id}: {e_sync}")
                    total_errors += 1

            # Check for new trades (from filled pending orders)
            new_on_platform = platform_position_ids - local_position_ids
            if new_on_platform:
                print(f"{log_prefix}Found {len(new_on_platform)} new position(s) on platform: {new_on_platform}")
                for position_id in new_on_platform:
                    position_data = next((pos for pos in platform_open_positions if str(pos.get('ticket')) == position_id), None)
                    if not position_data:
                        continue

                    try:
                        instrument = position_data.get('symbol')
                        volume = Decimal(str(position_data.get('volume')))
                        direction = "BUY" if position_data.get('type') == 0 else "SELL"
                        price = Decimal(str(position_data.get('price_open')))

                        # Find a matching pending order
                        pending_order = Order.objects.filter(
                            account=account,
                            instrument=instrument,
                            volume=volume,
                            direction=direction,
                            status='pending'
                        ).first()

                        if pending_order:
                            print(f"{log_prefix}Found matching pending order {pending_order.id} for new position {position_id}.")
                            pending_order.mark_filled(
                                price=price,
                                volume=volume,
                                broker_deal_id=int(position_id)
                            )
                            print(f"{log_prefix}Successfully created trade for new position {position_id}.")
                            total_synced += 1
                        else:
                            print(f"{log_prefix}No matching pending order found for new position {position_id}.")
                    except Exception as e_new_trade:
                        print(f"{log_prefix}Error processing new position {position_id}: {e_new_trade}")
                        total_errors += 1

        except Exception as e_account:
            print(f"{log_prefix}An unexpected error occurred while processing this account: {e_account}")
            import traceback
            traceback.print_exc()
            total_errors += 1

    print(f"{task_name} finished. Synced: {total_synced}, Errors: {total_errors}.")
    return f"{task_name}: Synced {total_synced}, Errors {total_errors}."


@shared_task(name="trades.tasks.synchronize_account_trades")
def synchronize_account_trades(account_id: int):
    """
    Synchronizes trades for a specific account on demand.
    """
    task_name = "synchronize_account_trades"
    print(f"CELERY TASK: {task_name} CALLED for account_id {account_id} at {timezone.now()}")

    try:
        account = Account.objects.get(id=account_id)
        mt5_account = MT5Account.objects.get(account=account)
    except (Account.DoesNotExist, MT5Account.DoesNotExist):
        print(f"{task_name}: Account or MT5Account not found for id {account_id}.")
        return f"{task_name}: Account or MT5Account not found."

    log_prefix = f"{task_name} (Account: {account.id}, MT5 Login: {mt5_account.account_number}): "
    total_synced = 0
    total_errors = 0

    local_open_trades = Trade.objects.filter(account=account, trade_status="open")

    if not local_open_trades.exists():
        print(f"{log_prefix}No open trades found in the database. Skipping.")
        return f"{task_name}: No open trades to sync."

    print(f"{log_prefix}Found {local_open_trades.count()} open trade(s) in DB. Checking against platform.")

    try:
        connector = MT5APIClient(
            base_url=settings.MT5_API_BASE_URL,
            account_id=mt5_account.account_number,
            password=mt5_account.encrypted_password,
            broker_server=mt5_account.broker_server,
            internal_account_id=str(account.id)
        )

        platform_positions_response = connector.get_all_open_positions_rest()
        if "error" in platform_positions_response:
            print(f"{log_prefix}Error fetching open positions from platform: {platform_positions_response['error']}")
            return f"{task_name}: Error fetching positions."

        platform_open_positions = platform_positions_response.get("open_positions", [])
        platform_position_ids = {str(pos['ticket']) for pos in platform_open_positions if 'ticket' in pos and pos.get('type') != 'pending_order'}
        print(f"{log_prefix}Found {len(platform_position_ids)} open position(s) on platform.")

        local_position_ids = {str(trade.position_id) for trade in local_open_trades if trade.position_id}
        closed_on_platform = local_position_ids - platform_position_ids

        for position_id in closed_on_platform:
            trade_to_sync = local_open_trades.get(position_id=position_id)
            print(f"{log_prefix}Discrepancy found! Trade {trade_to_sync.id} (PositionID: {position_id}) is 'open' locally but not on the platform. Triggering sync.")
            try:
                sync_result = synchronize_trade_with_platform(trade_id=trade_to_sync.id)
                if sync_result.get("error"):
                    print(f"{log_prefix}Error synchronizing trade {trade_to_sync.id}: {sync_result['error']}")
                    total_errors += 1
                else:
                    print(f"{log_prefix}Successfully synchronized trade {trade_to_sync.id}.")
                    total_synced += 1
            except Exception as e_sync:
                print(f"{log_prefix}Exception during synchronization for trade {trade_to_sync.id}: {e_sync}")
                total_errors += 1

    except Exception as e_account:
        print(f"{log_prefix}An unexpected error occurred while processing this account: {e_account}")
        import traceback
        traceback.print_exc()
        total_errors += 1

    print(f"{task_name} finished for account {account_id}. Synced: {total_synced}, Errors: {total_errors}.")
    return f"{task_name}: Synced {total_synced}, Errors {total_errors}."
