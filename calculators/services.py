def calc_required_hit_rate(growth_pct, risk_pct, num_trades, avg_winner_R):
    G = growth_pct / 100
    r = risk_pct   / 100
    N = num_trades
    A = avg_winner_R
    return (1 + G / (N * r)) / (1 + A)
