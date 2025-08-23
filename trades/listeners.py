from decimal import Decimal
<<<<<<< Updated upstream
from trading.models import Trade, Order
from asgiref.sync import sync_to_async

class PositionUpdateListener:
    @staticmethod
    @sync_to_async
    def on_position_update(trade_id, current_pnl):
        """
        Listener function to be called on every position update.
        Also updates runup/drawdown.
=======
from trading.models import Trade

class PositionUpdateListener:
    @staticmethod
    def on_position_update(trade_id, current_pnl):
        """
        Listener function to be called on every position update.
>>>>>>> Stashed changes
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
<<<<<<< Updated upstream
            # Trade may have been deleted
            pass

    @staticmethod
    @sync_to_async
    def tag_partial_close(trade_id, reason: str, subreason: str | None = None):
        """Tag the most recent filled Order for a trade (partial close)."""
        try:
            trade = Trade.objects.get(id=trade_id)
        except Trade.DoesNotExist:
            return
        last_order = (
            Order.objects.filter(trade=trade, status=Order.Status.FILLED)
            .order_by('-filled_at', '-created_at')
            .first()
        )
        if last_order:
            if not last_order.close_reason:
                last_order.close_reason = reason
                last_order.close_subreason = subreason
                last_order.save(update_fields=['close_reason', 'close_subreason'])

    @staticmethod
    @sync_to_async
    def tag_final_close(trade_id, reason: str, subreason: str | None = None):
        """Set the Trade close reason (final close)."""
        try:
            trade = Trade.objects.get(id=trade_id)
        except Trade.DoesNotExist:
            return
        update_fields = []
        if not trade.close_reason:
            trade.close_reason = reason
            update_fields.append('close_reason')
        if subreason is not None and not trade.close_subreason:
            trade.close_subreason = subreason
            update_fields.append('close_subreason')
        if update_fields:
            trade.save(update_fields=update_fields)

    @staticmethod
    async def process_new_positions(account, new_positions):
        """
        Process new positions to check for filled pending orders.
        """
=======
            # Handle the case where the trade does not exist
            pass

    @staticmethod
    def process_new_positions(account, new_positions):
        """
        Process new positions to check for filled pending orders.
        """
        # This is a placeholder for the actual implementation
>>>>>>> Stashed changes
        pass
