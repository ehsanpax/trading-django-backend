# ctrader_app/ctrader_client.py
import logging
from ctrader_open_api.client import Client
from ctrader_open_api.tcpProtocol import TcpProtocol
from ctrader_open_api.protobuf import Protobuf
from twisted.internet.asyncioreactor import install
from .utils import deferred_to_future
from .ctrader_service import ctrader_client

try:
    install()
except Exception:
    pass

logger = logging.getLogger("ctrader_client")
logging.basicConfig(level=logging.INFO)

class CTraderClient:
    def __init__(self, host, port, token, account_id, client_id, client_secret):
        self.host = host
        self.port = port
        self.token = token
        self.account_id = account_id
        self.client_id = client_id
        self.client_secret = client_secret
        
        self.client = ctrader_client

    async def authenticate_application(self):
        auth_req = Protobuf.get("ProtoOAApplicationAuthReq")
        auth_req.clientId = self.client_id
        auth_req.clientSecret = self.client_secret

        logger.info(f"[Application Auth] clientId: {self.client_id}, clientSecret: {self.client_secret}")
        response = await deferred_to_future(self.client.send(auth_req))
        logger.info(f"[Application Auth Response]: {response}")
        return response

    async def authenticate_account(self):
        account_auth_request = Protobuf.get("ProtoOAAccountAuthReq")
        account_auth_request.ctidTraderAccountId = self.account_id
        account_auth_request.accessToken = self.token

        logger.info(f"[Account Auth] ctidTraderAccountId: {self.account_id}, accessToken: {self.token}")
        response = await deferred_to_future(self.client.send(account_auth_request))
        logger.info(f"[Account Auth Response]: {response}")
        return response

    async def get_account_details(self):
        logger.info("[Connecting to cTrader]")
        await self.connect()

        logger.info("[Starting Application Auth]")
        await self.authenticate_application()

        logger.info("[Starting Account Auth]")
        await self.authenticate_account()

        trader_req = Protobuf.get("ProtoOATraderReq")
        trader_req.ctidTraderAccountId = self.account_id

        logger.info(f"[Trader Request] ctidTraderAccountId: {self.account_id}")
        response = await deferred_to_future(self.client.send(trader_req))
        trader_details = Protobuf.extract(response)
        logger.info(f"[Trader Response] Balance: {trader_details.trader.balance}")
        return trader_details.trader.balance

    async def connect(self):
        if not self.client.running:
            ctrader_client.startService()
            logger.info(f"[Connecting] Host: {self.host}, Port: {self.port}")
            conn = self.client.whenConnected()
            if hasattr(conn, "addCallbacks"):
                await deferred_to_future(conn)
            else:
                await conn
        logger.info("[Connected to cTrader API!]")


    async def get_open_positions(self):
        logger.info("[Fetching Open Positions]")
        # Make sure we’re connected and authenticated first
        await self.connect()
        await self.authenticate_application()
        await self.authenticate_account()

        # Prepare the request
        positions_req = Protobuf.get("ProtoOAGetAccountPositionsReq")
        positions_req.ctidTraderAccountId = self.account_id

        logger.info(f"[Positions Request] ctidTraderAccountId: {self.account_id}")
        response = await deferred_to_future(self.client.send(positions_req))
        
        # Parse the response
        positions_data = Protobuf.extract(response)
        # Typically this is a repeated field called `position`
        open_positions = getattr(positions_data, "position", [])

        logger.info(f"[Open Positions] Count: {len(open_positions)}")

        # Return in your preferred format
        return {"open_positions": open_positions}
