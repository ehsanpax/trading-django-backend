import asyncio
import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from asgiref.sync import sync_to_async
from accounts.models import Account, MT5Account, CTraderAccount
from rest_framework.authtoken.models import Token
import aiohttp
import websockets

class PriceConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.account_id = self.scope["url_route"]["kwargs"]["account_id"]
        self.symbol = self.scope["url_route"]["kwargs"]["symbol"]

        await self.accept()

        self.account = await sync_to_async(Account.objects.filter(id=self.account_id).first)()
        if not self.account:
            await self.send_json({"error": "Invalid account ID"})
            await self.close()
            return

        self.platform = self.account.platform.upper()

        # گرفتن توکن احراز هویت برای دسترسی به API
        try:
            token_obj = await sync_to_async(Token.objects.get)(user=self.account.user)
            self.api_token = token_obj.key
        except Token.DoesNotExist:
            await self.send_json({"error": "No API token found for user"})
            await self.close()
            return

        if self.platform == "MT5":
            self.price_task = asyncio.create_task(self.mt5_price_stream_via_api())

        elif self.platform == "CTRADER":
            ctrader_account = await sync_to_async(lambda: self.account.ctrader_account)()
            if not ctrader_account:
                await self.send_json({"error": "No linked CTRADER account found"})
                await self.close()
                return

            self.ctrader_access_token = ctrader_account.access_token
            self.ctid_trader_account_id = ctrader_account.ctid_trader_account_id
            if not self.ctrader_access_token or not self.ctid_trader_account_id:
                await self.send_json({"error": "Missing CTRADER credentials on account"})
                await self.close()
                return

            if not await self.subscribe_ctrader():
                await self.close()
                return

            self.price_task = asyncio.create_task(self.ctrader_price_stream())

        else:
            await self.send_json({"error": "Unsupported trading platform"})
            await self.close()

    async def disconnect(self, close_code):
        print(f"🔻 WebSocket disconnected for Account: {self.account_id} - {self.symbol}")
        if hasattr(self, "price_task"):
            self.price_task.cancel()
        print(f"🔻 WebSocket closed for Account: {self.account_id} - {self.symbol}")

    async def mt5_price_stream_via_api(self):
        try:
            while True:
                price_data = await self.get_mt5_price_from_api()
                await self.send_json(price_data)
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await self.send_json({"error": f"Exception in MT5 API stream: {str(e)}"})

    async def get_mt5_price_from_api(self):
        url = f"http://127.0.0.1:8000/api/mt5/market-price/{self.symbol}/{self.account_id}/"
        headers = {
            "Authorization": f"Token {self.api_token}"
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        return {"error": f"Failed to fetch price from API: {response.status}"}
            except Exception as e:
                return {"error": str(e)}

    async def subscribe_ctrader(self):
        subscription_url = "http://localhost:8080/ctrader/symbol/subscribe"
        payload = {
            "access_token": self.ctrader_access_token,
            "ctid_trader_account_id": self.ctid_trader_account_id,
            "symbol": self.symbol.upper()
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(subscription_url, json=payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        await self.send_json({"error": f"Subscription endpoint error: {error_text}"})
                        return False
                    return True
        except Exception as e:
            await self.send_json({"error": "Error calling subscription endpoint: " + str(e)})
            return False

    async def ctrader_price_stream(self):
        try:
            async with websockets.connect("ws://localhost:9000") as ws:
                greeting = await ws.recv()
                greeting_data = json.loads(greeting)
                if greeting_data.get("status") != "connected":
                    await self.send_json({"error": "Failed to connect to CTRADER live price server"})
                    return

                while True:
                    message = await ws.recv()
                    data = json.loads(message)
                    if data.get("symbol", "").upper() == self.symbol.upper():
                        await self.send_json({
                            "symbol": self.symbol.upper(),
                            "bid": data.get("bid"),
                            "ask": data.get("ask"),
                            "timestamp": data.get("timestamp")
                        })
        except Exception as e:
            await self.send_json({"error": "Error in CTRADER price stream: " + str(e)})
