from decimal import Decimal
from trading_platform.mt5_api_client import MT5APIClient
from django.conf import settings
# If/when available, import a connector for cTrader:
# from ctrader.services import CTraderConnector
from accounts.services import get_account_details

def get_total_open_pnl(account) -> Decimal:
    """
    Retrieves the total current P&L from open positions based on the account's platform.
    For MT5, it uses MT5Connector; for cTrader, similar logic would be applied.
    """
    total_open_pnl = Decimal('0.00')
    
    if account.platform.upper() == "MT5":
        try:
            mt5_account = account.mt5_account
        except Exception:
            return total_open_pnl

        client = MT5APIClient(
            base_url=settings.MT5_API_BASE_URL,
            account_id=mt5_account.account_number,
            password=mt5_account.encrypted_password,
            broker_server=mt5_account.broker_server,
            internal_account_id=str(account.id)
        )
        
        positions_response = client.get_open_positions()
        if "error" in positions_response:
            return total_open_pnl
        
        for pos in positions_response.get("open_positions", []):
            profit = pos.get("profit", 0)
            total_open_pnl += Decimal(str(profit))
    
    elif account.platform.upper() == "CTRADER":
        # Placeholder: Implement cTrader integration similarly when available.
        # Example:
        # ctrader_account = account.ctrader_account
        # connector = CTraderConnector(ctrader_account)
        # positions = connector.get_open_positions()
        # for pos in positions:
        #     total_open_pnl += Decimal(str(pos.get("profit", 0)))
        total_open_pnl = Decimal('0.00')
    
    else:
        total_open_pnl = Decimal('0.00')
    
    return total_open_pnl


def get_account_equity(account, user) -> Decimal:
    """
    Returns the current equity for an account by fetching up-to-date details from the broker.
    Falls back to the stored account.equity if fetching details fails.
    """
    details = get_account_details(account.id, user)
    if "error" not in details:
        return Decimal(details.get("equity", account.equity))
    # If there's an error fetching live data, fallback to stored equity.
    return Decimal(account.equity)
