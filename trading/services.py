from decimal import Decimal
from accounts.models import Account
from trading.models import Trade, EquityDataPoint

def calculate_equity_curve(account: Account):
    """
    Calculates and stores the equity curve for a given account.
    """
    # Delete existing data points to ensure a fresh calculation
    EquityDataPoint.objects.filter(account=account).delete()

    # Get the initial account balance
    initial_balance = account.balance
    current_equity = initial_balance

    # Get all closed trades for the account, ordered by close time
    closed_trades = Trade.objects.filter(
        account=account,
        trade_status='closed',
        closed_at__isnull=False
    ).order_by('closed_at')

    # Create the first data point with the initial balance
    if closed_trades.exists():
        first_trade_date = closed_trades.first().closed_at
        EquityDataPoint.objects.create(
            account=account,
            date=first_trade_date,
            equity=initial_balance
        )

    # Iterate through trades and create data points
    for trade in closed_trades:
        profit_loss = trade.actual_profit_loss or Decimal('0.0')
        current_equity += profit_loss
        EquityDataPoint.objects.update_or_create(
            account=account,
            date=trade.closed_at,
            defaults={'equity': current_equity}
        )

    return EquityDataPoint.objects.filter(account=account)
