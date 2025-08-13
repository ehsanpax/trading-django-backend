from decimal import Decimal
from accounts.models import Account
from trading.models import Trade

def calculate_equity_curve(account: Account):
    from trading.models import EquityDataPoint
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


def calculate_account_drawdown(account: Account):
    """
    Calculates the maximum drawdown for a given account.
    """
    from trading.models import TradePerformance

    equity_points = account.equity_data.order_by('date')
    peak_equity = 0
    max_drawdown = 0

    for point in equity_points:
        if point.equity > peak_equity:
            peak_equity = point.equity

        drawdown = (peak_equity - point.equity) / peak_equity * 100
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    # Update the TradePerformance model
    performance, created = TradePerformance.objects.get_or_create(user=account.user)
    performance.max_account_drawdown = max_drawdown
    performance.save(update_fields=['max_account_drawdown'])

    return max_drawdown
