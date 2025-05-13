from celery import shared_task
from .services import MT5Connector # Your modified connector
import MetaTrader5 as mt5 # Required for mt5.terminal_info() and mt5.shutdown() in finally
import os # To log process ID for confirmation

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
