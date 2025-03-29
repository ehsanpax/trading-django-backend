# price/consumers.py
import asyncio
import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from asgiref.sync import sync_to_async
from accounts.models import Account, MT5Account

class PriceConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.account_id = self.scope["url_route"]["kwargs"]["account_id"]
        self.symbol = self.scope["url_route"]["kwargs"]["symbol"]

        await self.accept()
        print(f"✅ WebSocket connection established for Account: {self.account_id} - {self.symbol}")

        # Fetch the account from the database (run sync ORM code in thread)
        self.account = await sync_to_async(Account.objects.filter(id=self.account_id).first)()
        if not self.account:
            await self.send_json({"error": "Invalid account ID"})
            await self.close()
            return

        self.platform = self.account.platform

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

            self.fetch_price = self.get_mt5_price
        else:
            await self.send_json({"error": "Unsupported trading platform"})
            await self.close()
            return

        self.price_task = asyncio.create_task(self.price_stream())

    async def disconnect(self, close_code):
        print(f"🔻 WebSocket disconnected for Account: {self.account_id} - {self.symbol}")
        if hasattr(self, "price_task"):
            self.price_task.cancel()
        import MetaTrader5 as mt5
        mt5.shutdown()
        print(f"🔻 WebSocket closed for Account: {self.account_id} - {self.symbol}")

    async def price_stream(self):
        try:
            while True:
                price_data = self.fetch_price(self.symbol)
                await self.send_json(price_data)
                await asyncio.sleep(1)
        except Exception as e:
            print(f"Error in price stream: {e}")

    def get_mt5_price(self, symbol):
        import MetaTrader5 as mt5
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            return {"symbol": symbol, "bid": tick.bid, "ask": tick.ask}
        return {"error": "Price data not available"}
