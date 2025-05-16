from celery import shared_task
from .services import MT5Connector
import MetaTrader5 as mt5
import os
from django.utils import timezone as django_timezone # Alias to avoid confusion
from decimal import Decimal
from datetime import datetime, timezone # Import timezone directly
from trading.models import Trade
from accounts.models import MT5Account
from django.db.models import Q
from trades.services import synchronize_trade_with_platform # Added import

@shared_task(bind=True, max_retries=3, default_retry_delay=60) # bind=True gives access to self for retries
def manage_mt5_account_operation(self, account_id: int, password: str, broker_server: str, operation: str, operation_params: dict = None):
    """
    A Celery task to connect to a specific MT5 account and perform an operation.
    - operation: string identifying the operation (e.g., 'get_account_info', 'place_trade')
    - operation_params: dict of parameters for the operation
    """
    process_id = os.getpid()
    task_id_str = f"Task ID: {self.request.id} " if self.request.id else ""
    log_prefix = f"[Celery {task_id_str}PID: {process_id}] Account {account_id} - "

    print(f"{log_prefix}Starting MT5 operation: {operation}")

    connector = None
    try:
        connector = MT5Connector(account_id=account_id, broker_server=broker_server)
        if not mt5.terminal_info():
            print(f"{log_prefix}Initial MT5 terminal_info check failed. Proceeding to connect which will attempt re-initialization.")

        login_result = connector.connect(password=password)

        if "error" in login_result:
            error_message = login_result['error']
            print(f"{log_prefix}Login failed: {error_message}")
            return {"status": "error", "message": f"Login failed: {error_message}"}

        print(f"{log_prefix}Successfully logged in.")

        result = None
        if operation == "get_account_info":
            result = connector.get_account_info()
        elif operation == "place_trade":
            if not operation_params:
                print(f"{log_prefix}Missing operation_params for place_trade")
                return {"status": "error", "message": "Missing operation_params for place_trade"}
            result = connector.place_trade(**operation_params)
        elif operation == "get_open_positions":
            result = connector.get_open_positions()
        elif operation == "close_trade":
            if not operation_params:
                print(f"{log_prefix}Missing operation_params for close_trade")
                return {"status": "error", "message": "Missing operation_params for close_trade"}
            result = connector.close_trade(**operation_params)
        else:
            print(f"{log_prefix}Unknown operation: {operation}")
            return {"status": "error", "message": f"Unknown operation: {operation}"}

        print(f"{log_prefix}Operation '{operation}' result: {result}")
        return {"status": "success", "data": result, "account_id": account_id, "process_id": process_id}

    except Exception as e:
        import traceback
        tb_str = traceback.format_exc()
        print(f"{log_prefix}Unhandled exception during MT5 operation '{operation}': {e}\n{tb_str}")
        return {"status": "error", "message": str(e), "account_id": account_id, "process_id": process_id}
    finally:
        if mt5.terminal_info(): 
            print(f"{log_prefix}Shutting down MT5 connection.")
            mt5.shutdown()
        else:
            print(f"{log_prefix}MT5 not initialized or already shut down, skipping shutdown call.")


@shared_task(name="mt5.tasks.monitor_mt5_stop_losses")
def monitor_mt5_stop_losses():
    """
    Periodically checks open MT5 trades to see if they have been closed on the platform,
    especially by Stop Loss, and updates the local database accordingly with confirmed details.
    """
    print(f"CELERY TASK: monitor_mt5_stop_losses INVOKED at {datetime.now()}") # Basic invocation check
    process_id = os.getpid()
    log_prefix = f"[Celery PID: {process_id}] MonitorMT5SL - "
    print(f"{log_prefix}Starting MT5 stop loss monitoring task.")

    open_mt5_trades = Trade.objects.filter(
        account__platform="MT5",
        trade_status="open",
        order_id__isnull=False
    ).select_related('account', 'account__mt5_account')

    if not open_mt5_trades.exists():
        print(f"{log_prefix}No open MT5 trades with order_id found to monitor.")
        return {"status": "success", "message": "No open MT5 trades to monitor."}

    updated_trades_count = 0
    skipped_trades_count = 0 

    trades_by_account = {}
    for trade in open_mt5_trades:
        if trade.account.id not in trades_by_account:
            trades_by_account[trade.account.id] = []
        trades_by_account[trade.account.id].append(trade)

    for account_id_key, trades_for_account in trades_by_account.items():
        if not trades_for_account:
            continue

        first_trade_in_group = trades_for_account[0]
        try:
            mt5_account_details = first_trade_in_group.account.mt5_account
        except MT5Account.DoesNotExist:
            print(f"{log_prefix}DEBUG: MT5Account.DoesNotExist for Account ID {first_trade_in_group.account.id}. Skipping trades for this account.")
            skipped_trades_count += len(trades_for_account)
            continue
        
        if not mt5_account_details:
            print(f"{log_prefix}DEBUG: MT5Account details (mt5_account_details is None) not found for Account ID {first_trade_in_group.account.id}. Skipping trades for this account.")
            skipped_trades_count += len(trades_for_account)
            continue
            
        connector = None
        try:
            print(f"{log_prefix}DEBUG: Processing account {mt5_account_details.account_number} on server {mt5_account_details.broker_server}")
            connector = MT5Connector(
                account_id=mt5_account_details.account_number,
                broker_server=mt5_account_details.broker_server
            )
            login_result = connector.connect(password=mt5_account_details.encrypted_password)

            if "error" in login_result:
                print(f"{log_prefix}DEBUG: Login failed for MT5 account {mt5_account_details.account_number}: {login_result['error']}. Skipping trades for this account.")
                skipped_trades_count += len(trades_for_account)
                if mt5.terminal_info(): mt5.shutdown()
                continue
            
            print(f"{log_prefix}DEBUG: Successfully logged into MT5 account {mt5_account_details.account_number}")

            for trade_to_check in trades_for_account:
                print(f"{log_prefix}DEBUG: Synchronizing trade {trade_to_check.id} (Position ID: {trade_to_check.position_id})")

                if not trade_to_check.position_id:
                    print(f"{log_prefix}DEBUG: Trade {trade_to_check.id} has no position_id. Cannot sync. Skipping.")
                    skipped_trades_count += 1
                    continue
                
                # Call the centralized synchronization function from trades.services
                # This function will handle fetching deals, creating new Order records for partials,
                # updating remaining_size, and updating trade status if fully closed.
                # It manages its own MT5 connection via MT5Connector.
                try:
                    # We pass trade_id and let the service function fetch the instance
                    # to ensure it works with the latest data, though we have trade_to_check here.
                    # This also decouples it further if synchronize_trade_with_platform is called from elsewhere.
                    sync_result = synchronize_trade_with_platform(trade_id=trade_to_check.id)
                    
                    if sync_result.get("error"):
                        print(f"{log_prefix}Error synchronizing trade {trade_to_check.id}: {sync_result.get('error')}")
                        skipped_trades_count += 1
                    else:
                        print(f"{log_prefix}Successfully synchronized trade {trade_to_check.id}. Result: {sync_result.get('message')}, Status: {sync_result.get('status')}")
                        # Check if the trade was updated to closed status by the sync function
                        # Re-fetch the trade instance to get the latest status after sync
                        updated_trade = Trade.objects.get(id=trade_to_check.id)
                        if updated_trade.trade_status == "closed" and trade_to_check.trade_status == "open": # trade_to_check is stale here
                             updated_trades_count += 1
                        elif updated_trade.trade_status == "open":
                             print(f"{log_prefix}Trade {updated_trade.id} remains open after sync.")
                        # If new orders (partials) were created, it's a successful sync action.
                        # The sync_result could be enhanced to indicate if new orders were created.
                        # For now, a successful call without error is considered a positive processing step.

                except Exception as sync_exc:
                    import traceback
                    tb_str_sync = traceback.format_exc()
                    print(f"{log_prefix}Unhandled exception during synchronize_trade_with_platform for trade {trade_to_check.id}: {sync_exc}\n{tb_str_sync}")
                    skipped_trades_count += 1
            
            # The MT5 connection for this account group is managed by the outer try/finally block.
            # synchronize_trade_with_platform creates its own connector instance and handles its lifecycle.
            # This means mt5.initialize/login/shutdown might happen per trade inside synchronize_trade_with_platform.
            # This is less efficient but ensures synchronize_trade_with_platform is self-contained.
            # The outer connector in this task is now primarily for the initial login check for the account group.

        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            print(f"{log_prefix}DEBUG: Unhandled exception while processing account {mt5_account_details.account_number if 'mt5_account_details' in locals() else 'UNKNOWN'}: {e}\n{tb_str}")
            skipped_trades_count += len(trades_for_account) 
        finally:
            if connector and mt5.terminal_info():
                print(f"{log_prefix}DEBUG: Shutting down MT5 connection for account {mt5_account_details.account_number if 'mt5_account_details' in locals() else 'N/A'}.")
                mt5.shutdown()
            elif mt5.terminal_info(): 
                print(f"{log_prefix}DEBUG: Shutting down MT5 connection (connector might have failed or was not used for all trades).")
                mt5.shutdown()

    print(f"{log_prefix}MT5 stop loss monitoring task finished. Updated: {updated_trades_count}, Skipped/Errors: {skipped_trades_count}.")
    return {"status": "success", "updated_trades": updated_trades_count, "skipped_trades": skipped_trades_count}
