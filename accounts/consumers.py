import json
import logging
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from asgiref.sync import sync_to_async
from django.conf import settings
from django.apps import apps
from .models import Account, MT5Account
from trading_platform.mt5_api_client import connection_manager
from trades.tasks import trigger_trade_synchronization
from trades.listeners import PositionUpdateListener
from monitoring.services import monitoring_service

logger = logging.getLogger(__name__)

class AccountConsumer(AsyncJsonWebsocketConsumer):
    """
    This consumer handles WebSocket connections for real-time account updates.
    It streams account balance, equity, and open positions by listening to the MT5APIClient.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.account_id = None
        self.user = None
        self.mt5_client = None
        self.is_active = False
        self.account_info = {}
        self.open_positions = []
        self.ticket_to_uuid_map = {}
        self.order_ticket_to_uuid_map = {}
        # Guard against duplicate enqueue for the same closed ticket in quick succession
        self._enqueued_closed_tickets = set()

    async def _populate_trade_uuid_map(self):
        """
        Queries the database for all open trades for the current account
        and populates the ticket-to-UUID mapping.
        """
        Trade = apps.get_model('trading', 'Trade')
        #logger.info(f"Populating trade UUID map for account {self.account_id}")
        open_trades = await sync_to_async(list)(
            Trade.objects.filter(
                account_id=self.account_id,
                trade_status='open'
            ).values('position_id', 'id')
        )
        self.ticket_to_uuid_map = {
            str(trade['position_id']): str(trade['id']) for trade in open_trades
        }
        #logger.info(f"UUID map populated with {len(self.ticket_to_uuid_map)} entries.")

    async def _populate_order_uuid_map(self):
        """
        Queries the database for all pending orders for the current account
        and populates the order ticket-to-UUID mapping.
        """
        Order = apps.get_model('trading', 'Order')
        #logger.info(f"Populating order UUID map for account {self.account_id}")
        pending_orders_db = await sync_to_async(list)(
            Order.objects.filter(
                account_id=self.account_id,
                status='pending'
            ).values('broker_order_id', 'id')
        )
        self.order_ticket_to_uuid_map = {
            str(order['broker_order_id']): str(order['id']) for order in pending_orders_db
        }
        #logger.info(f"Order UUID map populated with {len(self.order_ticket_to_uuid_map)} entries.")

    async def connect(self):
        """
        Handles a new WebSocket connection.
        """
        self.user = self.scope["user"]
        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        self.account_id = self.scope["url_route"]["kwargs"]["account_id"]
        
        try:
            account = await sync_to_async(Account.objects.select_related('mt5_account').get)(id=self.account_id, user=self.user)
            if account.platform != "MT5":
                logger.warning(f"Attempted WebSocket connection for non-MT5 account {self.account_id}.")
                await self.close(code=4004, reason="Real-time updates are only supported for MT5 accounts.")
                return
            mt5_account = account.mt5_account
        except (Account.DoesNotExist, MT5Account.DoesNotExist):
            await self.close(code=4003, reason="Account not found.")
            return

        await self.accept()
        self.is_active = True
        logger.info(f"Account WebSocket connected for account {self.account_id}")

        monitoring_service.register_connection(
            self.channel_name,
            self.user,
            self.account_id,
            "account",
            {}
        )

        self.mt5_client = await connection_manager.get_client(
            base_url=settings.MT5_API_BASE_URL,
            account_id=mt5_account.account_number,
            password=mt5_account.encrypted_password,
            broker_server=mt5_account.broker_server,
            internal_account_id=str(account.id)
        )

        # Trigger the MT5 instance initialization
        await self.mt5_client.trigger_instance_initialization()

        # Register listeners
        self.mt5_client.register_account_info_listener(self.send_account_update)
        self.mt5_client.register_open_positions_listener(self.send_positions_update)

        # Send initial state from cache immediately
        logger.info(f"Populating initial UUID maps and sending cached data for account {self.account_id}")
        await self._populate_trade_uuid_map()
        await self._populate_order_uuid_map()
        self.account_info = self.mt5_client.get_account_info()
        all_positions = self.mt5_client.get_open_positions().get("open_positions", [])
        pending_orders = [p for p in all_positions if isinstance(p, dict) and p.get('type') == 'pending_order']
        self.open_positions = [p for p in all_positions if isinstance(p, dict) and p.get('type') != 'pending_order']
        await self.send_combined_update(pending_orders=pending_orders)

    async def disconnect(self, close_code):
        """
        Handles a WebSocket disconnection.
        """
        monitoring_service.unregister_connection(self.channel_name)
        self.is_active = False
        if self.mt5_client:
            self.mt5_client.unregister_account_info_listener(self.send_account_update)
            self.mt5_client.unregister_open_positions_listener(self.send_positions_update)
        logger.info(f"Account WebSocket disconnected for account {self.account_id}")

    async def receive_json(self, content):
        """
        Handles incoming messages from the client.
        """
        monitoring_service.update_client_message(self.channel_name, content)
        action = content.get("action")
        if action == "unsubscribe":
            logger.info(f"Unsubscribe request received for account {self.account_id}. Closing connection.")
            await self.close()

    async def send_account_update(self, account_info):
        """Callback for account info updates from the MT5APIClient."""
        if not self.is_active:
            return
        self.account_info = account_info
        await self.send_combined_update()

    async def send_positions_update(self, open_positions):
        """Callback for open positions updates from the MT5APIClient."""
        if not self.is_active:
            return
        all_positions = open_positions
        pending_orders = [p for p in all_positions if isinstance(p, dict) and p.get('type') == 'pending_order']
        open_trades = [p for p in all_positions if isinstance(p, dict) and p.get('type') != 'pending_order']

        self.open_positions = open_trades

        # --- Efficiently check if the pending order list has changed ---
        current_order_tickets = {str(p['ticket']) for p in pending_orders if p and 'ticket' in p}
        previous_order_tickets = set(self.order_ticket_to_uuid_map.keys())

        if current_order_tickets != previous_order_tickets:
            #logger.info("Change in pending orders detected. Refreshing order UUID map from DB.")
            await self._populate_order_uuid_map()

        await self.send_combined_update(pending_orders=pending_orders)

        # --- Continue with existing logic for open trades ---
        current_trade_tickets = {str(pos.get('ticket')) for pos in self.open_positions}
        previous_trade_tickets = set(self.ticket_to_uuid_map.keys())

        closed_tickets = previous_trade_tickets - current_trade_tickets
        if closed_tickets:
            logger.info(f"Detected {len(closed_tickets)} closed trades: {closed_tickets}")
            for ticket in closed_tickets:
                # Prevent duplicate enqueues for the same ticket
                if ticket in self._enqueued_closed_tickets:
                    continue
                trade_id = self.ticket_to_uuid_map.get(ticket)
                if trade_id:
                    logger.info(f"Enqueuing synchronization task for closed trade. Ticket: {ticket}, Trade ID: {trade_id}")
                    self._enqueued_closed_tickets.add(ticket)
                    trigger_trade_synchronization.apply_async(kwargs={'trade_id': trade_id})
                    if ticket in self.ticket_to_uuid_map:
                        del self.ticket_to_uuid_map[ticket]
                else:
                    logger.warning(f"Could not find trade_id for closed ticket {ticket} in map.")

        new_tickets = current_trade_tickets - previous_trade_tickets
        if new_tickets:
            logger.info(f"Detected {len(new_tickets)} new trades: {new_tickets}")
            new_positions_data = [pos for pos in self.open_positions if str(pos.get('ticket')) in new_tickets]
            
            # Get the account instance
            account = await sync_to_async(Account.objects.get)(id=self.account_id)
            
            # Process these new positions to check for filled pending orders
            await PositionUpdateListener.process_new_positions(account, new_positions_data)

        # After processing, refresh the trade UUID map to include the new trades
        #logger.info("Refreshing trade UUID map from DB after processing new trades.")
        await self._populate_trade_uuid_map()

        # --- Update drawdown and run-up for each open trade ---
        for pos in self.open_positions:
            trade_id = self.ticket_to_uuid_map.get(str(pos.get('ticket')))
            if trade_id:
                await PositionUpdateListener.on_position_update(
                    trade_id, pos.get('profit', 0)
                )

    async def send_combined_update(self, pending_orders: list = []):
        """Combines the latest account info, positions, and pending orders and sends to the client."""
        if not self.account_info:
            logger.debug(f"Skipping update for {self.account_id} because account_info is empty.")
            return

        # Process open positions
        processed_positions = []
        for pos_item in self.open_positions:
            if isinstance(pos_item, dict):
                ticket_value = pos_item.get('ticket')
                if ticket_value is not None:
                    processed_positions.append({
                        **pos_item,
                        'trade_id': self.ticket_to_uuid_map.get(str(ticket_value))
                    })
                else:
                    processed_positions.append(pos_item)

        # Process pending orders to inject UUID
        processed_pending_orders = []
        for order_item in pending_orders:
            if isinstance(order_item, dict):
                ticket_value = order_item.get('ticket')
                if ticket_value is not None:
                    processed_pending_orders.append({
                        **order_item,
                        'order_id': self.order_ticket_to_uuid_map.get(str(ticket_value))
                    })
                else:
                    processed_pending_orders.append(order_item)

        payload = {
            "type": "account_update",
            "data": {
                "balance": self.account_info.get("balance"),
                "equity": self.account_info.get("equity"),
                "margin": self.account_info.get("margin"),
                "open_positions": processed_positions,
                "pending_orders": processed_pending_orders
            }
        }
        await self.send_json(payload)
        monitoring_service.update_server_message(self.channel_name, payload)
