from decimal import Decimal
from trading.models import Trade

class PositionUpdateListener:
    @staticmethod
    def on_position_update(trade_id, current_pnl):
        """
        Listener function to be called on every position update.
        """
        try:
            trade = Trade.objects.get(id=trade_id)
            current_pnl = Decimal(current_pnl)

            # Update max_runup
            if trade.max_runup is None or current_pnl > trade.max_runup:
                trade.max_runup = current_pnl

            # Update max_drawdown
            if trade.max_drawdown is None or current_pnl < trade.max_drawdown:
                trade.max_drawdown = current_pnl

            trade.save(update_fields=['max_runup', 'max_drawdown'])

        except Trade.DoesNotExist:
            # Handle the case where the trade does not exist
            pass

    @staticmethod
    def process_new_positions(account, new_positions):
        """
        Process new positions to check for filled pending orders.
        """
        # This is a placeholder for the actual implementation
        pass
