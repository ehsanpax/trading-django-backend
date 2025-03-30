import MetaTrader5 as mt5
from datetime import datetime, timedelta
import time # Good practice to have

def list_recent_historical_deals(days_history=90):
    """
    Connects to MetaTrader 5 and lists historical deals within a specified
    number of past days, showing deal ticket and order ticket.

    Args:
        days_history (int): How many days back to fetch history from. Defaults to 90.

    Returns:
        None: Prints the details directly or an error message.
    """
    print(f"Attempting to list historical deals from the last {days_history} days...")

    # Establish connection to the MetaTrader 5 terminal
    if not mt5.initialize():
        print(f"initialize() failed, error code = {mt5.last_error()}")
        mt5.shutdown()
        return

    print(f"MetaTrader 5 version: {mt5.version()}")

    # Calculate the date range for fetching history
    # Note: MetaTrader uses server time. Ensure your specified date range makes sense.
    # Current time is calculated based on the system running the script.
    date_to = datetime.now()
    date_from = date_to - timedelta(days=days_history)

    print(f"Fetching deals from {date_from.strftime('%Y-%m-%d %H:%M:%S')} to {date_to.strftime('%Y-%m-%d %H:%M:%S')}")

    deals = None
    try:
        # Fetch deals for all symbols (*) within the date range
        deals = mt5.history_deals_get(date_from, date_to, group="*")

    except Exception as e:
        print(f"Error calling history_deals_get: {e}")
        mt5.shutdown()
        return

    # Check if the call was successful and if deals were returned
    if deals is None:
        print(f"Could not retrieve history deals, error code = {mt5.last_error()}")
    elif len(deals) == 0:
        print(f"No historical deals found in the last {days_history} days.")
    else:
        print(f"\nFound {len(deals)} deals in the last {days_history} days:")
        print("-" * 100)
        # Header - adjust spacing as needed
        print(f"{'Deal Ticket':<12} | {'Order Ticket':<12} | {'Time (UTC)':<20} | {'Symbol':<10} | {'Type':<4} | {'Volume':<8} | {'Price':<10} | {'Profit':<10}")
        print("-" * 100)

        # Iterate through the deals and print relevant info
        for deal in deals:
            # Determine Buy/Sell based on deal type
            deal_type_str = "Buy" if deal.type == mt5.DEAL_TYPE_BUY else ("Sell" if deal.type == mt5.DEAL_TYPE_SELL else str(deal.type))
            # Format time - MT5 times are usually UTC timestamps
            deal_time_str = datetime.fromtimestamp(deal.time).strftime('%Y-%m-%d %H:%M:%S')

            print(f"{deal.ticket:<12} | {deal.order:<12} | {deal_time_str:<20} | {deal.symbol:<10} | {deal_type_str:<4} | {deal.volume:<8.2f} | {deal.price:<10.5f} | {deal.profit:<10.2f}")

        print("-" * 100)

    # Terminate connection to the MetaTrader 5 terminal
    mt5.shutdown()
    print("\nMetaTrader 5 connection closed.")


# --- Main execution ---
if __name__ == "__main__":
    # You can change the number of days here if needed
    days_to_fetch = 90
    # Alternatively, ask the user:
    # try:
    #     days_input = input(f"Enter number of days history to fetch (default {days_to_fetch}): ")
    #     if days_input:
    #          days_to_fetch = int(days_input)
    # except ValueError:
    #     print("Invalid input, using default.")

    try:
        list_recent_historical_deals(days_history=days_to_fetch)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        # Ensure shutdown in case of unexpected error before initialize completes
        mt5.shutdown()