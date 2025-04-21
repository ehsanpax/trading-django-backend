# price/consumers.py
import asyncio
import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from asgiref.sync import sync_to_async
from accounts.models import Account, MT5Account, CTraderAccount
import websockets, aiohttp
class PriceConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.account_id = self.scope["url_route"]["kwargs"]["account_id"]
        self.symbol = self.scope["url_route"]["kwargs"]["symbol"]

        await self.accept()
        #print(f"✅ WebSocket connection established for Account: {self.account_id} - {self.symbol}")

        # Fetch the account from the database using async ORM (via sync_to_async)
        self.account = await sync_to_async(Account.objects.filter(id=self.account_id).first)()
        if not self.account:
            await self.send_json({"error": "Invalid account ID"})
            await self.close()
            return

        self.platform = self.account.platform.upper()

        if self.platform == "MT5":
            self.mt5_account = await sync_to_async(MT5Account.objects.filter(account_id=self.account.id).first)()
            if not self.mt5_account:
                await self.send_json({"error": "No MT5 account found"})
                await self.close()
                return

            # Initialize MT5
            import MetaTrader5 as mt5
            if not mt5.initialize():
                await self.send_json({"error": "Failed to initialize MT5"})
                await self.close()
                return

            # For MT5, use the existing synchronous price fetching function wrapped in our loop
            self.fetch_price = self.get_mt5_price
            self.price_task = asyncio.create_task(self.price_stream())

        elif self.platform == "CTRADER":
            #print("...CTRADER PRICE FEED....")
            # Retrieve the linked cTrader account from the related field in a thread
            ctrader_account = await sync_to_async(lambda: self.account.ctrader_account)()
            if not ctrader_account:
                await self.send_json({"error": "No linked CTRADER account found"})
                await self.close()
                return

            # Extract credentials from the instance
            self.ctrader_access_token = ctrader_account.access_token
            self.ctid_trader_account_id = ctrader_account.ctid_trader_account_id
            if not self.ctrader_access_token or not self.ctid_trader_account_id:
                await self.send_json({"error": "Missing CTRADER credentials on account"})
                await self.close()
                return

            # Now trigger the subscription by calling the REST endpoint.
            if not await self.subscribe_ctrader():
                await self.close()
                return

            # Once the subscription is successful, start the price stream.
            self.price_task = asyncio.create_task(self.ctrader_price_stream())

        else:
            await self.send_json({"error": "Unsupported trading platform"})
            await self.close()
            return

    async def disconnect(self, close_code):
        print(f"🔻 WebSocket disconnected for Account: {self.account_id} - {self.symbol}")
        if hasattr(self, "price_task"):
            self.price_task.cancel()
        if self.platform == "MT5":
            import MetaTrader5 as mt5
            mt5.shutdown()
            print(f"🔻 MT5 session shutdown for Account: {self.account_id}")
        print(f"🔻 WebSocket closed for Account: {self.account_id} - {self.symbol}")

    async def price_stream(self):
        # MT5 price stream loop (unchanged)
        try:
            while True:
                price_data = self.get_mt5_price(self.symbol)
                await self.send_json(price_data)
                await asyncio.sleep(1)
        except Exception as e:
            print(f"Error in MT5 price stream: {e}")

    def get_mt5_price(self, symbol):
        import MetaTrader5 as mt5
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            return {"symbol": symbol, "bid": tick.bid, "ask": tick.ask}
        return {"error": "Price data not available"}

    async def subscribe_ctrader(self):
        """
        Calls the CTRADER REST subscription endpoint to trigger live price subscription.
        Expected endpoint: POST http://localhost:8000/ctrader/symbol/subscribe
        Payload includes access token, ctid trader account id, and symbol.
        """
        subscription_url = "http://localhost:8080/ctrader/symbol/subscribe"
        payload = {
            "access_token": self.ctrader_access_token,
            "ctid_trader_account_id": self.ctid_trader_account_id,
            "symbol": self.symbol.upper()
        }
        #print("CALLING CTRADER SUBSCRIPTION ENDPOINT..AT:", subscription_url)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(subscription_url, json=payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        await self.send_json({"error": f"Subscription endpoint error: {error_text}"})
                        return False
                    # You can also check returned JSON if needed.
                    data = await response.json()
                    #print(f"Subscription successful: {data}")
                    return True
        except Exception as e:
            await self.send_json({"error": "Error calling subscription endpoint: " + str(e)})
            return False

    async def ctrader_price_stream(self):
        """
        Opens an asynchronous connection to the CTRADER WebSocket endpoint (ws://localhost:9000)
        and continuously listens for price updates.
        """
        try:
            async with websockets.connect("ws://localhost:9000") as ws:
                # Wait for connection confirmation from CTRADER server
                greeting = await ws.recv()
                greeting_data = json.loads(greeting)
                if greeting_data.get("status") != "connected":
                    await self.send_json({"error": "Failed to connect to CTRADER live price server"})
                    return

                # Listen indefinitely for price updates
                while True:
                    message = await ws.recv()
                    data = json.loads(message)
                    # Forward updates that match the requested symbol
                    if data.get("symbol", "").upper() == self.symbol.upper():
                        await self.send_json({
                            "symbol": self.symbol.upper(),
                            "bid": data.get("bid"),
                            "ask": data.get("ask"),
                            "timestamp": data.get("timestamp")
                        })
        except Exception as e:
            await self.send_json({"error": "Error in CTRADER price stream: " + str(e)})