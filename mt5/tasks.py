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
        # The MT5Connector __init__ already attempts to initialize.
        # We can check terminal_info here to see if initialization in __init__ was successful.
        if not mt5.terminal_info():
            # This implies initialization in MT5Connector.__init__ failed.
            # The error would have been printed there. We can return an error or attempt connect which will re-try init.
            print(f"{log_prefix}Initial MT5 terminal_info check failed. Proceeding to connect which will attempt re-initialization.")

        login_result = connector.connect(password=password)

        if "error" in login_result:
            error_message = login_result['error']
            print(f"{log_prefix}Login failed: {error_message}")
            # Example of retrying for specific, potentially transient errors
            # if "authentication failed" in error_message.lower() or "invalid account" in error_message.lower():
            #     # Don't retry for auth errors, it's likely a permanent issue with credentials/account
            #     return {"status": "error", "message": f"Login failed: {error_message}"}
            # else:
            #     # For other types of login errors (e.g., connection issues), retry
            #     raise self.retry(exc=Exception(f"Login failed: {error_message}"), countdown=self.default_retry_delay)
            return {"status": "error", "message": f"Login failed: {error_message}"}


        print(f"{log_prefix}Successfully logged in.")

        # Perform the requested operation
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
        # Add more operations as needed:
        # elif operation == "get_position_by_ticket":
        #     if not operation_params or "ticket" not in operation_params:
        #         return {"status": "error", "message": "Missing 'ticket' in operation_params for get_position_by_ticket"}
        #     result = connector.get_position_by_ticket(ticket=operation_params["ticket"])
        # elif operation == "get_closed_trade_profit":
        #      if not operation_params or "order_ticket" not in operation_params:
        #         return {"status": "error", "message": "Missing 'order_ticket' in operation_params for get_closed_trade_profit"}
        #      result = connector.get_closed_trade_profit(order_ticket=operation_params["order_ticket"])
        else:
            print(f"{log_prefix}Unknown operation: {operation}")
            return {"status": "error", "message": f"Unknown operation: {operation}"}

        print(f"{log_prefix}Operation '{operation}' result: {result}")
        return {"status": "success", "data": result, "account_id": account_id, "process_id": process_id}

    except Exception as e:
        # Catch any other unexpected exceptions
        import traceback
        tb_str = traceback.format_exc()
        print(f"{log_prefix}Unhandled exception during MT5 operation '{operation}': {e}\n{tb_str}")
        # Decide if retry is appropriate for generic exceptions
        # raise self.retry(exc=e, countdown=self.default_retry_delay)
        return {"status": "error", "message": str(e), "account_id": account_id, "process_id": process_id}
    finally:
        # Ensure MT5 is shut down for this worker process, regardless of success or failure.
        # Check if mt5 was initialized in this process before trying to shut down.
        if mt5.terminal_info(): 
            print(f"{log_prefix}Shutting down MT5 connection.")
            mt5.shutdown()
        else:
            print(f"{log_prefix}MT5 not initialized or already shut down, skipping shutdown call.")


@shared_task(name="mt5.tasks.monitor_mt5_stop_losses")
def monitor_mt5_stop_losses():
    """
    Periodically checks open MT5 trades to see if they have been closed on the platform,
    especially by Stop Loss, and updates the local database accordingly.
    """
    process_id = os.getpid()
    log_prefix = f"[Celery PID: {process_id}] MonitorMT5SL - "
    print(f"{log_prefix}Starting MT5 stop loss monitoring task.")

    open_mt5_trades = Trade.objects.filter(
        account__platform="MT5",
        trade_status="open",
        order_id__isnull=False  # Ensure we have an order_id to check against
    ).select_related('account', 'account__mt5_account')

    if not open_mt5_trades.exists():
        print(f"{log_prefix}No open MT5 trades with order_id found to monitor.")
        return {"status": "success", "message": "No open MT5 trades to monitor."}

    updated_trades_count = 0
    errors_count = 0

    # Group trades by account to minimize MT5 connections
    trades_by_account = {}
    for trade in open_mt5_trades:
        if trade.account.id not in trades_by_account:
            trades_by_account[trade.account.id] = []
        trades_by_account[trade.account.id].append(trade)

    for account_id_key, trades_for_account in trades_by_account.items():
        if not trades_for_account:
            continue

        # Get MT5 account details for connection from the first trade in the group
        # (all trades in this group share the same parent Account)
        first_trade_in_group = trades_for_account[0]
        try:
            mt5_account_details = first_trade_in_group.account.mt5_account
            if not mt5_account_details: # Should not happen if select_related worked and data is consistent
                print(f"{log_prefix}MT5Account details not found for Account ID {first_trade_in_group.account.id}. Skipping trades for this account.")
                errors_count += len(trades_for_account)
                continue
        except MT5Account.DoesNotExist:
            print(f"{log_prefix}MT5Account.DoesNotExist for Account ID {first_trade_in_group.account.id}. Skipping trades for this account.")
            errors_count += len(trades_for_account)
            continue
        
        connector = None
        try:
            print(f"{log_prefix}Processing account {mt5_account_details.account_number} on server {mt5_account_details.broker_server}")
            connector = MT5Connector(
                account_id=mt5_account_details.account_number,
                broker_server=mt5_account_details.broker_server
            )
            login_result = connector.connect(password=mt5_account_details.encrypted_password)

            if "error" in login_result:
                print(f"{log_prefix}Login failed for MT5 account {mt5_account_details.account_number}: {login_result['error']}. Skipping trades for this account.")
                errors_count += len(trades_for_account)
                if mt5.terminal_info(): mt5.shutdown() # Ensure shutdown if login failed but init happened
                continue

            for trade_to_check in trades_for_account:
                print(f"{log_prefix}Checking trade {trade_to_check.id} (Order ID: {trade_to_check.order_id})")
                
                # Check if position still exists (is open) on MT5
                # This is a quick check. If it's not found, it's likely closed.
                position_info = connector.get_position_by_ticket(trade_to_check.order_id)
                
                if position_info and not position_info.get("error"):
                    # Position is still open on MT5, no action needed for this trade.
                    print(f"{log_prefix}Trade {trade_to_check.id} (Order ID: {trade_to_check.order_id}) is still open on MT5.")
                    continue
                
                # If position_info has an error like "No open position found", it means it's closed.
                # Now, get detailed closing information.
                closing_details = connector.get_closing_deal_details_for_order(order_ticket=trade_to_check.order_id)

                if "error" in closing_details:
                    # This could mean no deals found, or history_deals_get failed.
                    # If "No explicit closing deal found", it might be an issue with how it was closed or timing.
                    # If "No deals found for order", it's also problematic.
                    # We should log this but might not mark the trade as closed in DB unless we are sure.
                    # For now, if we can't get closing details, we assume it's not definitively closed by SL/TP for DB update.
                    print(f"{log_prefix}Could not get closing details for trade {trade_to_check.id} (Order ID: {trade_to_check.order_id}): {closing_details['error']}")
                    # errors_count += 1 # Not necessarily an error if the trade is simply not closed yet or closed manually without SL/TP record
                    continue # Skip updating this trade if we can't confirm closure details

                # If we have closing details, update the trade in our database
                trade_to_check.trade_status = "closed"
                trade_to_check.actual_profit_loss = Decimal(str(closing_details.get("net_profit", 0)))
                trade_to_check.commission = Decimal(str(closing_details.get("commission", 0))) # Assuming commission is part of net_profit
                trade_to_check.swap = Decimal(str(closing_details.get("swap", 0))) # Assuming swap is part of net_profit
                
                close_time_str = closing_details.get("close_time")
                if close_time_str:
                    trade_to_check.closed_at = timezone.make_aware(datetime.fromisoformat(close_time_str.replace("Z", "+00:00")), timezone.utc)
                else:
                    trade_to_check.closed_at = timezone.now() # Fallback

                # Optionally, add a note if closed by SL/TP to the trade's reason or a new field
                if closing_details.get("closed_by_sl"):
                    trade_to_check.reason = (trade_to_check.reason or "") + " Closed by Stop Loss on MT5."
                    print(f"{log_prefix}Trade {trade_to_check.id} closed by SL. P&L: {trade_to_check.actual_profit_loss}")
                elif closing_details.get("closed_by_tp"):
                    trade_to_check.reason = (trade_to_check.reason or "") + " Closed by Take Profit on MT5."
                    print(f"{log_prefix}Trade {trade_to_check.id} closed by TP. P&L: {trade_to_check.actual_profit_loss}")
                else:
                    print(f"{log_prefix}Trade {trade_to_check.id} closed (Reason code: {closing_details.get('reason_code')}). P&L: {trade_to_check.actual_profit_loss}")
                
                trade_to_check.save()
                updated_trades_count += 1
                print(f"{log_prefix}Updated trade {trade_to_check.id} in database.")

        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            print(f"{log_prefix}Unhandled exception while processing account {mt5_account_details.account_number if 'mt5_account_details' in locals() else 'UNKNOWN'}: {e}\n{tb_str}")
            errors_count += len(trades_for_account) # Assume all trades for this account failed if connector setup fails
        finally:
            if connector and mt5.terminal_info():
                print(f"{log_prefix}Shutting down MT5 connection for account {mt5_account_details.account_number if 'mt5_account_details' in locals() else 'N/A'}.")
                mt5.shutdown()
            elif mt5.terminal_info(): # If connector failed but mt5 was initialized
                print(f"{log_prefix}Shutting down MT5 connection (connector might have failed).")
                mt5.shutdown()


    print(f"{log_prefix}MT5 stop loss monitoring task finished. Updated: {updated_trades_count}, Errors/Skipped: {errors_count}.")
    return {"status": "success", "updated_trades": updated_trades_count, "errors_skipped": errors_count}
