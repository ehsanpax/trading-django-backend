# connectors/ctrader_connector.py

import logging
import threading

# Twisted imports
from twisted.internet import reactor, defer
from twisted.internet.threads import blockingCallFromThread
from twisted.internet import task

# OpenApiPy imports
from ctrader_open_api import Client, EndPoints, TcpProtocol, Protobuf
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq,
    ProtoOAAccountAuthReq,
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOAErrorRes,
)
from google.protobuf.json_format import MessageToDict


logger = logging.getLogger(__name__)


"""def start_twisted_reactor():
    if not reactor.running:
        reactor_thread = threading.Thread(
            target=reactor.run, kwargs={'installSignalHandlers': 0}, daemon=True
        )
        reactor_thread.start()
        logger.info("Twisted reactor started in a separate thread.")"""


class CTraderConnector:
    """
    A connector class that wraps the OpenApiPy Client for connecting to cTrader Open API.
    Provides both async and sync methods for retrieving account information.
    """

    def __init__(self, is_live=False):
        self.is_live = is_live
        self.client = None

    """"def start_service(self):
    
        #Initializes the client and starts the Twisted service. 
        # Ensure the Twisted reactor is running.
        start_twisted_reactor()
        host = EndPoints.PROTOBUF_LIVE_HOST if self.is_live else EndPoints.PROTOBUF_DEMO_HOST
        port = EndPoints.PROTOBUF_PORT
        self.client = Client(host, port, TcpProtocol)
        self.client.setConnectedCallback(self.on_connected)
        self.client.setDisconnectedCallback(self.on_disconnected)
        self.client.setMessageReceivedCallback(self.on_message_received)

        self.client.startService()
        logger.info("cTrader client service started on %s:%s", host, port)"""

    # --------------------
    # Callbacks / Handlers
    # --------------------

    #def on_connected(self, client):
    #    logger.info("Connected to cTrader API.")
    #    self.send_application_auth("13641_QqAQIxv5R7wUGHoSjbKTalzNMPbyDEt6b9I8VxgwUO3rs3qN0P", "tFzXEFQi2fYtaIWm7xdz54n6jhnT5dQHGT82Jf5Z3J6DSUwV1i")

    def on_disconnected(self, client, reason):
        logger.error("Disconnected from cTrader API: %s", reason)

    def on_message_received(self, client, message):
        logger.debug("Message received: %s", message)

    # --------------------
    # Application Auth
    # --------------------

    def send_application_auth(self, client_id, client_secret):
        """
        Sends the initial application-level authentication request (ProtoOAApplicationAuthReq).
        This is necessary so that cTrader recognizes your clientId/clientSecret before further requests.
        """
        req = ProtoOAApplicationAuthReq()
        req.clientId = client_id
        req.clientSecret = client_secret

        d = self.client.send(req)
        d.addCallback(self._handle_auth_response)
        d.addErrback(self._handle_auth_error)
        return d

    def _handle_auth_response(self, response):
        logger.info("Application Auth response: %s", response)

    def _handle_auth_error(self, failure):
        logger.error("Application Auth error: %s", failure)

    # --------------------
    # Account Auth + Info
    # --------------------
    def on_message_received(self, client, message):
        # Show the payloadType
        logger.info("on_message_received: payloadType=%s clientMsgId=%s", 
                    message.payloadType, 
                    message.clientMsgId)
        # Optionally extract the entire message with Protobuf or MessageToDict
        from google.protobuf.json_format import MessageToDict
        from ctrader_open_api import Protobuf

        # Method A: direct Protobuf.extract
        # data = Protobuf.extract(message)
        # logger.info("Protobuf.extract: %s", data)

        # Method B: google.protobuf.json_format
        # msg_dict = MessageToDict(message, preserving_proto_field_name=True)
        # logger.info("MessageToDict: %s", msg_dict)

    def authorize_account_async(self, access_token, ctid_trader_account_id):
        """
        Tells cTrader that this specific trading account (ctid_trader_account_id)
        is authorized by the given access_token.
        """
        req = ProtoOAAccountAuthReq()
        req.accessToken = access_token
        req.ctidTraderAccountId = ctid_trader_account_id

        d = self.client.send(req)

        # Just log the response for debugging
        def _on_auth_ok(r):
            logger.info("Account authorized, response: %s", r)
            return r

        d.addCallback(_on_auth_ok)
        return d





    def _process_account_list_response(self, response, account_id):
        """
        Process the ProtoOAGetAccountListByAccessTokenRes proto object by converting it into a dictionary.
        """
        from google.protobuf.json_format import MessageToDict
        # Check for error responses first.
        if isinstance(response, ProtoOAErrorRes):
            raise Exception(f"cTrader returned error: {response.description}")

        # Convert the Protobuf message into a dict.
        data = MessageToDict(response, preserving_proto_field_name=True)
        logger.info("Extracted data from response: %s", data)

        # The response should contain a list under a key, e.g. "ctidTraderAccount" or "accounts".
        account_list = data.get("ctidTraderAccount") or data.get("accounts") or []
        logger.info("Parsed account list: %s", account_list)

        # Loop through the list to find the matching account.
        for acct in account_list:
            acct_id = acct.get("ctidTraderAccountId") or acct.get("accountId")
            if str(acct_id) == str(account_id):
                return {
                    "balance": acct.get("balance"),
                    "equity": acct.get("equity"),
                    "margin": acct.get("margin"),
                    "open_positions": [],
                }
        return {}




    def get_account_info_sync(self, access_token, account_id):
        """
        A synchronous/blocking version of get_account_info_async,
        used in Django sync views by calling blockingCallFromThread.
        """
        def _fetch():
            return self.get_account_info_async(access_token, account_id)

        return blockingCallFromThread(reactor, _fetch)


# -----------------------
# Global instance
# -----------------------
# In many Django or FastAPI apps, you create a single, shared connector at import time.
ctrader_connector = CTraderConnector(is_live=False)
ctrader_connector.start_service()
