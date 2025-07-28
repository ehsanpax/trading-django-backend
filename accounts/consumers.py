import json
import logging
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from asgiref.sync import sync_to_async
from django.conf import settings
from django.apps import apps
from .models import Account, MT5Account
from trading_platform.mt5_api_client import connection_manager

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
        self.account_info = {}
        self.open_positions = []
        self.ticket_to_uuid_map = {}

    async def _populate_trade_uuid_map(self):
        """
        Queries the database for all open trades for the current account
        and populates the ticket-to-UUID mapping.
        """
        Trade = apps.get_model('trading', 'Trade')
        logger.info(f"Populating trade UUID map for account {self.account_id}")
        open_trades = await sync_to_async(list)(
            Trade.objects.filter(
                account_id=self.account_id,
                trade_status='open'
            ).values('position_id', 'id')
        )
        self.ticket_to_uuid_map = {
            str(trade['position_id']): str(trade['id']) for trade in open_trades
        }
        logger.info(f"UUID map populated with {len(self.ticket_to_uuid_map)} entries.")

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
                # For now, we only support MT5 real-time updates via this consumer.
                # cTrader would require a different listener mechanism.
                logger.warning(f"Attempted WebSocket connection for non-MT5 account {self.account_id}.")
                await self.close(code=4004, reason="Real-time updates are only supported for MT5 accounts.")
                return
            mt5_account = account.mt5_account
        except (Account.DoesNotExist, MT5Account.DoesNotExist):
            await self.close(code=4003, reason="Account not found.")
            return

        await self.accept()
        logger.info(f"Account WebSocket connected for account {self.account_id}")

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
        logger.info(f"Populating initial UUID map and sending cached data for account {self.account_id}")
        await self._populate_trade_uuid_map()
        self.account_info = self.mt5_client.get_account_info()
        self.open_positions = self.mt5_client.get_open_positions().get("open_positions", [])
        await self.send_combined_update()

    async def disconnect(self, close_code):
        """
        Handles a WebSocket disconnection.
        """
        if self.mt5_client:
            self.mt5_client.unregister_account_info_listener(self.send_account_update)
            self.mt5_client.unregister_open_positions_listener(self.send_positions_update)
        logger.info(f"Account WebSocket disconnected for account {self.account_id}")

    async def receive_json(self, content):
        """
        Handles incoming messages from the client.
        """
        action = content.get("action")
        if action == "unsubscribe":
            logger.info(f"Unsubscribe request received for account {self.account_id}. Closing connection.")
            await self.close()

    async def send_account_update(self, account_info):
        """Callback for account info updates from the MT5APIClient."""
        self.account_info = account_info
        await self.send_combined_update()

    async def send_positions_update(self, open_positions):
        """Callback for open positions updates from the MT5APIClient."""
        # open_positions is already the list of positions from MT5APIClient
        self.open_positions = open_positions
        
        # Check if any new positions are not in our map
        found_new_trade = False
        for pos in self.open_positions:
            # Ensure pos is a dictionary before trying .get()
            if isinstance(pos, dict) and str(pos.get('ticket')) not in self.ticket_to_uuid_map:
                found_new_trade = True
                break
        
        if found_new_trade:
            logger.info("New position ticket detected, refreshing UUID map.")
            await self._populate_trade_uuid_map()

        await self.send_combined_update()

    async def send_combined_update(self):
        """Combines the latest account info and positions and sends to the client."""
        if not self.account_info: # Don't send empty updates if the initial cache is empty
            logger.debug(f"Skipping update for {self.account_id} because account_info is empty.")
            return

        # The MT5APIClient is now responsible for ensuring self.open_positions is a list of dicts.
        # We can remove the redundant type checking here.

        # The MT5APIClient is now responsible for ensuring self.open_positions is a list of dicts.
        # We can remove the redundant type checking here.

        # Add extreme logging for each element in open_positions
        # This logging is crucial to understand the exact type of each item
        for i, pos_item in enumerate(self.open_positions):
            logger.error(f"send_combined_update: Element {i} type: {type(pos_item)}, content: {pos_item}")

        # Process positions with extreme defensive parsing
        processed_positions = []
        for pos_item in self.open_positions:
            current_pos_dict = None
            if isinstance(pos_item, str):
                try:
                    current_pos_dict = json.loads(pos_item)
                    if not isinstance(current_pos_dict, dict):
                        logger.error(f"send_combined_update: Parsed string is not a dict: {pos_item}")
                        current_pos_dict = None # Reset if not a dict
                except json.JSONDecodeError as e:
                    logger.error(f"send_combined_update: Failed to parse string element: {pos_item}. Error: {e}")
                    current_pos_dict = None # Reset on error
            elif isinstance(pos_item, dict):
                current_pos_dict = pos_item
            else:
                logger.error(f"send_combined_update: Unexpected type for position element: {type(pos_item)} - {pos_item}")
                current_pos_dict = None # Reset for unexpected types

            if current_pos_dict:
                # Ensure 'ticket' key exists before trying to get it
                ticket_value = current_pos_dict.get('ticket')
                if ticket_value is not None:
                    processed_positions.append({
                        **current_pos_dict,
                        'trade_id': self.ticket_to_uuid_map.get(str(ticket_value))
                    })
                else:
                    logger.warning(f"send_combined_update: Position dict missing 'ticket' key: {current_pos_dict}")
                    processed_positions.append(current_pos_dict) # Add without trade_id if ticket is missing
            
        payload = {
            "type": "account_update",
            "data": {
                "balance": self.account_info.get("balance"),
                "equity": self.account_info.get("equity"),
                "margin": self.account_info.get("margin"),
                "open_positions": processed_positions
            }
        }
        #logger.info(f"Sending account update to client for account {self.account_id}")
        await self.send_json(payload)
