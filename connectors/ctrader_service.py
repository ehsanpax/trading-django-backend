# ctrader_app/ctrader_client.py
import logging
from ctrader_open_api.client import Client
from ctrader_open_api.tcpProtocol import TcpProtocol
from ctrader_open_api.protobuf import Protobuf
from twisted.internet.asyncioreactor import install
from .utils import deferred_to_future
from ctrader_open_api import Client, Protobuf, TcpProtocol, Auth, EndPoints
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *
from twisted.internet import reactor
import threading
import asyncio

from ctrader_open_api import messages
messages.TimeOut = 15
# Global reference to the single client instance
ctrader_client = None

def _start_ctrader_client():
    global ctrader_client

    if ctrader_client is not None:
        return ctrader_client  # Already started

    def connected():
        print("Connected to cTrader")

    def disconnected():
        print("Disconnected from cTrader")

    def on_message_received(message):
        print("Received:", message)

    print("Setting up ctrader client")
    ctrader_client = Client(host="demo.ctraderapi.com", port=5035, protocol=TcpProtocol)
    ctrader_client.setConnectedCallback(connected)
    ctrader_client.setDisconnectedCallback(disconnected)
    ctrader_client.setMessageReceivedCallback(on_message_received)
    threading.Thread(target=ctrader_client.startService, args=()).start()

    print("ctrader client setup finished")


    return ctrader_client

# Actually create/run it on module import
_start_ctrader_client()
