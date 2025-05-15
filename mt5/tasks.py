from celery import shared_task
from .services import MT5Connector
import MetaTrader5 as mt5
import os
from django.utils import timezone
from decimal import Decimal
from datetime import datetime
from trading.models import Trade 
from accounts.models import MT5Account
from django.db.models import Q

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
                print(f"{log_prefix}DEBUG: Checking trade {trade_to_check.id} (Order ID: {trade_to_check.order_id})")
                
                position_info = connector.get_position_by_ticket(trade_to_check.order_id)
                print(f"{log_prefix}DEBUG: Response from get_position_by_ticket for order {trade_to_check.order_id}: {position_info}")
                
                # Condition evaluation:
                # position_info is truthy (not None, not empty dict) AND 'error' key is NOT in position_info
                is_still_open = bool(position_info and not position_info.get("error"))
                print(f"{log_prefix}DEBUG: Trade {trade_to_check.id} - Is still open based on position_info? {is_still_open}")

                if is_still_open:
                    print(f"{log_prefix}Trade {trade_to_check.id} (Order ID: {trade_to_check.order_id}) is still open on MT5. Skipping.")
                    continue
                
                print(f"{log_prefix}Trade {trade_to_check.id} (Order ID: {trade_to_check.order_id}) appears closed on MT5 (or get_position_by_ticket failed). Attempting to fetch closing deal details...")
                closing_details = connector.get_closing_deal_details_for_order(order_ticket=trade_to_check.order_id)
                print(f"{log_prefix}DEBUG: Response from get_closing_deal_details_for_order for order {trade_to_check.order_id}: {closing_details}")

                has_closing_error = "error" in closing_details
                print(f"{log_prefix}DEBUG: Trade {trade_to_check.id} - Has error in closing_details? {has_closing_error}")

                if has_closing_error:
                    print(f"{log_prefix}Trade {trade_to_check.id} (Order ID: {trade_to_check.order_id}): Not in open positions, but failed to retrieve closing deal details: {closing_details['error']}. Will retry in next cycle.")
                    skipped_trades_count += 1 
                    continue 
                else:
                    print(f"{log_prefix}Trade {trade_to_check.id} (Order ID: {trade_to_check.order_id}): Closing deal details found. Updating database.")
                    trade_to_check.trade_status = "closed"
                    trade_to_check.actual_profit_loss = Decimal(str(closing_details.get("net_profit", 0)))
                    trade_to_check.commission = Decimal(str(closing_details.get("commission", 0)))
                    trade_to_check.swap = Decimal(str(closing_details.get("swap", 0)))
                    
                    close_time_str = closing_details.get("close_time")
                    if close_time_str:
                        try:
                            dt_obj = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
                            if dt_obj.tzinfo is None or dt_obj.tzinfo.utcoffset(dt_obj) is None: 
                                trade_to_check.closed_at = timezone.make_aware(dt_obj, timezone.utc)
                            else: 
                                trade_to_check.closed_at = dt_obj.astimezone(timezone.utc)
                        except ValueError:
                            print(f"{log_prefix}DEBUG: Error parsing close_time_str '{close_time_str}' for trade {trade_to_check.id}. Using current time as fallback.")
                            trade_to_check.closed_at = timezone.now()
                    else:
                        print(f"{log_prefix}DEBUG: No close_time in details for trade {trade_to_check.id}. Using current time as fallback.")
                        trade_to_check.closed_at = timezone.now()

                    reason_suffix = ""
                    if closing_details.get("closed_by_sl"):
                        reason_suffix = " Closed by Stop Loss on MT5."
                    elif closing_details.get("closed_by_tp"):
                        reason_suffix = " Closed by Take Profit on MT5."
                    else:
                        reason_suffix = f" Closed on MT5 (Reason code: {closing_details.get('reason_code')})."
                    
                    print(f"{log_prefix}DEBUG: Trade {trade_to_check.id} - Reason Suffix: '{reason_suffix.strip()}' P&L: {trade_to_check.actual_profit_loss}")
                    
                    current_reason = trade_to_check.reason or ""
                    if reason_suffix.strip() and reason_suffix.strip() not in current_reason:
                        trade_to_check.reason = (current_reason + reason_suffix).strip()
                
                    trade_to_check.save()
                    updated_trades_count += 1
                    print(f"{log_prefix}Updated trade {trade_to_check.id} in database with confirmed closure details.")

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
