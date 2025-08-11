import numpy as np
import pandas as pd
from decimal import Decimal, ROUND_DOWN

def calculate_portfolio_stats(equity_curve: list, trades_log: list) -> dict:
    """
    Calculates advanced portfolio statistics from an equity curve and trade log.

    :param equity_curve: A list of dictionaries, e.g., [{'timestamp': '...', 'equity': ...}]
    :param trades_log: A list of dictionaries representing closed trades.
    :return: A dictionary of calculated statistics.
    """
    if not equity_curve:
        return {}

    equity_series = pd.Series(
        [p['equity'] for p in equity_curve],
        index=pd.to_datetime([p['timestamp'] for p in equity_curve])
    ).astype(float)

    if equity_series.empty:
        return {}

    # 1. Drawdown calculations
    high_water_mark = equity_series.cummax()
    drawdown = high_water_mark - equity_series
    drawdown_pct = (drawdown / high_water_mark).replace([np.inf, -np.inf], 0)
    
    max_drawdown_val = drawdown.max()
    max_drawdown_pct = drawdown_pct.max()

    # 2. Returns calculations
    total_return_pct = (equity_series.iloc[-1] / equity_series.iloc[0]) - 1
    daily_returns = equity_series.resample('D').last().pct_change().dropna()
    
    # 3. Risk-Adjusted Returns (assuming 0 risk-free rate)
    sharpe_ratio = 0
    if daily_returns.std() > 0:
        # Annualized Sharpe Ratio
        sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)

    downside_returns = daily_returns[daily_returns < 0]
    sortino_ratio = 0
    if downside_returns.std() > 0:
        sortino_ratio = (daily_returns.mean() / downside_returns.std()) * np.sqrt(252)

    calmar_ratio = 0
    if max_drawdown_pct > 0:
        # Annualized return
        days = (equity_series.index[-1] - equity_series.index[0]).days
        annualized_return = ((1 + total_return_pct) ** (365.0 / days)) - 1 if days > 0 else 0
        calmar_ratio = annualized_return / max_drawdown_pct

    # 4. Trade statistics
    if not trades_log:
        return {
            "max_drawdown": float(max_drawdown_val),
            "max_drawdown_pct": float(max_drawdown_pct),
            "total_return_pct": float(total_return_pct),
            "sharpe_ratio": float(sharpe_ratio),
            "sortino_ratio": float(sortino_ratio),
            "calmar_ratio": float(calmar_ratio),
            "total_trades": 0,
        }

    pnl_values = [Decimal(str(t.get('pnl', 0))) for t in trades_log]
    
    winning_trades = [p for p in pnl_values if p > 0]
    losing_trades = [p for p in pnl_values if p < 0]

    win_rate = len(winning_trades) / len(pnl_values) if pnl_values else 0
    
    total_profit = sum(winning_trades)
    total_loss = abs(sum(losing_trades))

    profit_factor = float(total_profit / total_loss) if total_loss > 0 else 0

    average_win = total_profit / len(winning_trades) if winning_trades else Decimal(0)
    average_loss = total_loss / len(losing_trades) if losing_trades else Decimal(0)
    
    expectancy = (win_rate * float(average_win)) - ((1 - win_rate) * float(average_loss))

    # 5. Detailed trade stats
    long_trades = [t for t in trades_log if t.get('side') == 'BUY']
    short_trades = [t for t in trades_log if t.get('side') == 'SELL']

    biggest_win = max(pnl_values) if winning_trades else Decimal(0)
    biggest_loss = min(pnl_values) if losing_trades else Decimal(0)

    max_consecutive_wins = 0
    max_consecutive_losses = 0
    current_win_streak = 0
    current_loss_streak = 0
    for pnl in pnl_values:
        if pnl > 0:
            current_win_streak += 1
            current_loss_streak = 0
        else:
            current_loss_streak += 1
            current_win_streak = 0
        max_consecutive_wins = max(max_consecutive_wins, current_win_streak)
        max_consecutive_losses = max(max_consecutive_losses, current_loss_streak)

    return {
        "max_drawdown": float(max_drawdown_val),
        "max_drawdown_pct": float(max_drawdown_pct),
        "total_return_pct": float(total_return_pct),
        "sharpe_ratio": float(sharpe_ratio),
        "sortino_ratio": float(sortino_ratio),
        "calmar_ratio": float(calmar_ratio),
        "profit_factor": float(profit_factor),
        "expectancy": float(expectancy),
        "win_rate": float(win_rate),
        "average_win": float(average_win),
        "average_loss": float(average_loss),
        "total_trades": len(pnl_values),
        "long_trades_count": len(long_trades),
        "short_trades_count": len(short_trades),
        "biggest_win": float(biggest_win),
        "biggest_loss": float(biggest_loss),
        "max_consecutive_wins": max_consecutive_wins,
        "max_consecutive_losses": max_consecutive_losses,
    }
