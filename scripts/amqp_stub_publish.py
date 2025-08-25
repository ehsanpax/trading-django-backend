import os
import asyncio
import json
import argparse

try:
    import aio_pika
except Exception:
    aio_pika = None


def parse_args():
    p = argparse.ArgumentParser(description="Stub AMQP publisher for bots feed smoke testing")
    p.add_argument("account_id", help="Internal account UUID to route messages to")
    p.add_argument("symbol", help="Symbol, e.g., EURUSD")
    p.add_argument("timeframe", help="Timeframe, e.g., M1", nargs="?", default="M1")
    p.add_argument("--exchange", default=os.getenv("AMQP_EVENTS_EXCHANGE", "mt5.events"))
    p.add_argument("--url", default=os.getenv("AMQP_URL", "amqp://guest:guest@localhost:5672/%2F"))
    return p.parse_args()


async def main_async(args):
    if aio_pika is None:
        raise RuntimeError("aio-pika not installed; please install to use this script")
    conn = await aio_pika.connect_robust(args.url)
    try:
        channel = await conn.channel()
        await channel.set_qos(prefetch_count=10)
        exchange = await channel.declare_exchange(args.exchange, aio_pika.ExchangeType.TOPIC, durable=True)
        # Tick message
        tick = {
            "type": "price.tick",
            "payload": {"symbol": args.symbol, "bid": 1.2345, "ask": 1.2347, "last": 1.2346, "time": 1699999999}
        }
        await exchange.publish(aio_pika.Message(body=json.dumps(tick).encode("utf-8")), routing_key=f"account.{args.account_id}.price.tick")
        # Candle message
        candle = {
            "type": "candle.update",
            "payload": {"symbol": args.symbol, "timeframe": args.timeframe, "candle": {"time": 1699999999, "open": 1.23, "high": 1.24, "low": 1.22, "close": 1.235, "volume": 1234}}
        }
        await exchange.publish(aio_pika.Message(body=json.dumps(candle).encode("utf-8")), routing_key=f"account.{args.account_id}.candle.update")
        print("Published tick and candle stub messages.")
    finally:
        await conn.close()


def main():
    args = parse_args()
    asyncio.get_event_loop().run_until_complete(main_async(args))


if __name__ == "__main__":
    main()
