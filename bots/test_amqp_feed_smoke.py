import os
import asyncio
import unittest
from unittest import skipUnless

from django.test import TestCase
from django.contrib.auth import get_user_model

try:
    import aio_pika  # noqa: F401
    AIO_PIKA_AVAILABLE = True
except Exception:
    AIO_PIKA_AVAILABLE = False

from accounts.models import Account
from bots.feeds import AMQPFeed


def env_ready():
    return bool(os.getenv("AMQP_URL")) and AIO_PIKA_AVAILABLE


@skipUnless(env_ready(), "AMQP smoke disabled (missing AMQP_URL or aio-pika)")
class AMQPFeedSmokeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="amqpuser", password="x")
        self.account = Account.objects.create(user=self.user, name="AMQP Acc", platform="MT5", balance=10000, equity=10000)
        self.exchange = os.getenv("AMQP_EVENTS_EXCHANGE", "mt5.events")
        self.url = os.getenv("AMQP_URL")

    async def _publish_tick_and_candle(self, symbol: str, timeframe: str):
        conn = await aio_pika.connect_robust(self.url)
        try:
            channel = await conn.channel()
            await channel.set_qos(prefetch_count=10)
            exchange = await channel.declare_exchange(self.exchange, aio_pika.ExchangeType.TOPIC, durable=True)
            # Tick
            tick_payload = {
                "type": "price.tick",
                "payload": {"symbol": symbol, "bid": 1.2345, "ask": 1.2347, "last": 1.2346, "time": 1699999999}
            }
            rk_tick = f"account.{self.account.id}.price.tick"
            await exchange.publish(aio_pika.Message(body=__import__("json").dumps(tick_payload).encode("utf-8")), routing_key=rk_tick)
            # Candle
            candle_payload = {
                "type": "candle.update",
                "payload": {"symbol": symbol, "timeframe": timeframe, "candle": {"time": 1699999999, "open": 1.23, "high": 1.24, "low": 1.22, "close": 1.235, "volume": 1234}}
            }
            rk_candle = f"account.{self.account.id}.candle.update"
            await exchange.publish(aio_pika.Message(body=__import__("json").dumps(candle_payload).encode("utf-8")), routing_key=rk_candle)
        finally:
            await conn.close()

    def test_amqp_feed_receives_messages(self):
        symbol = "EURUSD"
        timeframe = "M1"
        feed = AMQPFeed(str(self.account.id), symbol, timeframe)
        feed.start()
        # Publish asynchronously
        asyncio.get_event_loop().run_until_complete(self._publish_tick_and_candle(symbol, timeframe))
        # Try to read two events within a short window
        got = []
        import time
        deadline = time.time() + 5
        while time.time() < deadline and len(got) < 2:
            evt = feed.get_event(timeout=0.5)
            if evt:
                got.append(evt.get("type"))
        feed.stop()
        self.assertTrue("tick" in got or "candle" in got, f"No events received: {got}")
