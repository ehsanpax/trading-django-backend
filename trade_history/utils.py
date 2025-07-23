from trading.models import ProfitTarget

BROKER_DEAL_REASON_CODES_MT5 = {
    0: "Client Terminal",  # DEAL_REASON_CLIENT
    1: "Mobile Application",  # DEAL_REASON_MOBILE
    2: "Web Platform",  # DEAL_REASON_WEB
    3: "Expert Advisor/Script",  # DEAL_REASON_EXPERT
    4: "Stop Loss Hit",  # DEAL_REASON_SL
    5: "Take Profit Hit",  # DEAL_REASON_TP
    6: "Stop Out",  # DEAL_REASON_SO
    7: "Rollover",  # DEAL_REASON_ROLLOVER
    8: "Variation Margin",  # DEAL_REASON_VMARGIN
    9: "Instrument Split",  # DEAL_REASON_SPLIT
    10: "Corporate Action"  # DEAL_REASON_CORPORATE_ACTION
}

def get_mt5_deal_reason(order, trade_profit_targets):
    """
    Determines a human-readable reason for an MT5 deal (Order).

    :param order: The Order instance from trading.models.
    :param trade_profit_targets: A queryset or list of ProfitTarget instances related to the order's trade.
    :return: A string representing the deal reason.
    """
    if order.broker_deal_reason_code is None:
        return "Reason Not Specified"

    reason_code = order.broker_deal_reason_code

    if reason_code == 5:  # DEAL_REASON_TP (Take Profit)
        if order.filled_price is not None and trade_profit_targets:
            for pt in trade_profit_targets:
                if pt.target_price == order.filled_price and pt.status == 'hit':
                    return f"TP{pt.rank} Hit"
        return BROKER_DEAL_REASON_CODES_MT5.get(reason_code, "Take Profit (General)")

    return BROKER_DEAL_REASON_CODES_MT5.get(reason_code, f"Unknown Reason Code: {reason_code}")
