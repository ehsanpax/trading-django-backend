import logging
from decimal import Decimal
from asgiref.sync import sync_to_async
from django.apps import apps

logger = logging.getLogger(__name__)

class PositionUpdateListener:
    @staticmethod
    async def process_new_positions(account, new_positions: list):
        """
        Processes newly detected open positions to find and mark corresponding
        pending orders as filled.
        """
        Order = apps.get_model('trading', 'Order')
        
        for position in new_positions:
            try:
                # Extract relevant details from the new position
                position_ticket = position.get('ticket')
                instrument = position.get('symbol')
                volume = Decimal(str(position.get('volume')))
                direction = "BUY" if position.get('type') == 0 else "SELL" # MT5 specific: 0 for buy, 1 for sell
                price = Decimal(str(position.get('price_open')))
                
                if not all([position_ticket, instrument, volume, direction, price]):
                    logger.warning(f"Skipping new position due to missing data: {position}")
                    continue

                # Find a matching pending order in the database
                # The match is based on account, instrument, volume, and direction.
                # This assumes that we don't have multiple identical pending orders.
                matching_order = await sync_to_async(Order.objects.filter(
                    account=account,
                    instrument=instrument,
                    volume=volume,
                    direction=direction,
                    status='pending'
                ).first)()

                if matching_order:
                    logger.info(f"Found matching pending order {matching_order.id} for new position {position_ticket}.")
                    
                    # Use the order's mark_filled method to create the trade
                    await sync_to_async(matching_order.mark_filled)(
                        price=price,
                        volume=volume,
                        broker_deal_id=position_ticket # Assuming the position ticket is the deal ID
                    )
                    logger.info(f"Successfully marked order {matching_order.id} as filled and created trade.")
                else:
                    logger.info(f"No matching pending order found for new position {position_ticket}.")

            except Exception as e:
                logger.error(f"Error processing new position {position.get('ticket')}: {e}")
